# Plantwise — Architectural Decisions

This document captures the key architectural decisions made for Plantwise,
including the reasoning behind each choice, the tradeoffs accepted, and
what would change in a production system.

---

## 1. Data model: relational schema derived from the API structure

### Decision
The raw `data.zip` exports (API-style JSON + financial CSVs) are normalized into
a relational schema that mirrors the source hierarchy but is shaped for querying,
tenancy, and document generation:

```
companies (company_id PK, display_name)
users     (user_id PK, company_id FK, email, role, access_scope)

plants    (id PK, company_id FK, name, unique_id,
           nominal_power_kw, region, commissioning_date)   -- Parameters[] flattened
elements  (id PK, plant_id FK, unique_id, name, type, type_string)
datasources (id PK, element_id FK, plant_id FK, company_id FK,
             name, units, aggregation_type)                -- sum / average
datapoints (datasource_id FK, company_id FK, ts, value)    -- hourly time series

market_prices (company_id FK, zone, ts, eur_per_mwh)       -- financial
monthly_costs (company_id FK, plant_id FK, year, month,
               category, amount_eur, notes)                -- financial
```

The source IDs (`1001`, `100101`, …) are kept as natural primary keys — they are
already globally unique across the dataset and keeping them makes the ingested
data traceable back to the raw exports.

### Reasoning

**Hierarchy preserved.** The source is a clean tree — company → plant → element →
datasource → datapoint — and the schema keeps that tree with explicit foreign keys.
This is what lets the agent answer questions like "energy by plant" or "which
inverter underperformed" with straightforward joins.

**Plant `Parameters[]` flattened to typed columns.** The raw plant export carries
parameters as a key/value array (`Nominal Power`, `Region`, `Commissioning Date`).
These are flattened into typed columns (`nominal_power_kw NUMERIC`, `region TEXT`,
`commissioning_date DATE`). The parameter set is small and stable across both
companies, and typed columns are far easier for the agent to filter, sort, and
aggregate on than digging into a JSONB blob. The agent writes cleaner SQL and the
column types prevent it from comparing a power rating as a string.

**Datasource carries its `aggregation_type`.** Each datasource in the source is
exported with a fixed aggregation (`sum` for energy totalizers, `average` for
instantaneous metrics like power, irradiance, temperature). Storing this on the
`datasources` row tells the agent how a metric should be aggregated over time
without it having to guess — summing an average-type series would be wrong.

**Datapoints: one flat, narrow table.** Hourly readings across many datasources
are stored as `(datasource_id, ts, value)` — one row per reading — with a composite
index on `(datasource_id, ts)`. This is the right shape for the analytical queries
the agent runs (filter by datasource, range by time) and extends cleanly when new
datasources appear, unlike a pivoted wide table that would break the moment two
plants expose different metrics. For this dataset's volume, a standard B-tree index
is sufficient — no time-series extension is justified.

**`company_id` denormalized onto tenant-scoped rows.** `datasources` and
`datapoints` carry a redundant `company_id` even though it is derivable through the
plant join. This is deliberate: it lets the RLS policy on every table be a direct
column check (`company_id = current_setting('app.current_company_id')`) with no
join, which keeps both the policy and the query planner simple. See Decision 2.

### What would change in production
- Add a TimescaleDB hypertable (or native partitioning) on `datapoints` once the
  reading volume grows beyond what a single B-tree index serves comfortably,
  partitioning by time for cheap retention and faster range scans.
- Keep a raw landing table (or object storage) of the original JSON/CSV so
  re-ingestion is reproducible and the normalization can be replayed after a
  schema change.
- Add ingestion-time validation (units, expected datasource set per plant,
  duplicate timestamps) with a quarantine path for malformed rows.

---

## 2. Multi-tenancy: shared database with Row-Level Security

### Decision
Single PostgreSQL database with RLS policies enforced via session variables.

```sql
SET LOCAL app.current_company_id = ?;
SET LOCAL app.current_access_scope = ?;  -- energy | energy+financial
SET LOCAL app.current_role = ?;          -- admin | operator
```

### Reasoning
The critical requirement is that isolation holds even if the agent receives
an adversarial or malformed instruction. Enforcing isolation at the DB layer
means the agent cannot return another company's data even if it tries — Postgres
simply has no rows to return outside the current session scope.

App-level filtering (WHERE company_id = ? in every query) would work but
creates a class of bugs where a missing WHERE clause silently leaks data.
RLS makes the correct behavior the default.

`SET LOCAL` inside a transaction is the correct primitive here: the variable
is automatically reset on commit, which prevents session pollution across
requests in a connection pool.

### Isolation dimensions
After examining the data, `role` and `access_scope` turned out to be **orthogonal**
and must not be conflated — the source carries them as two independent columns:

- **company_id** — hard boundary. Never crossable, regardless of role or scope.
  Enforced by an RLS policy on every tenant-scoped table.
- **access_scope** — *what data you can see*. Financial tables (`market_prices`,
  `monthly_costs`, and any derived revenue) are gated by an RLS policy requiring
  `app.current_access_scope = 'energy+financial'`. An `energy`-only user gets zero
  rows from those tables — at the DB layer, not in application code. This holds for
  admin and operator alike: scope is independent of role.
- **role** (admin / operator) — *what you can do*. This governs action-level logic
  (e.g. which agent tools are available), carried as a session variable but **not**
  the gate for financial data. A scope-financial operator sees financials; a
  scope-energy admin does not.

This is a correction to an earlier assumption that financials were gated by role.
The data's explicit `access_scope` field and the README ("energy-only users should
not be able to access financial data") make scope the correct boundary.

### What would change in production
- Evaluate `pgBouncer` in transaction mode with explicit `SET LOCAL` to safely
  use connection pooling at scale.
- Consider separate DB users per role (e.g. `app_readonly`, `app_admin`) as a
  second layer: even a direct connection with leaked credentials would be
  constrained by Postgres-level permissions, not just RLS policies.
- Add RLS audit logging to detect policy violations or unexpected access patterns.

---

## 3. Authentication: fake login with X-User-ID header

### Decision
No JWT or session tokens. The UI presents a user selector dropdown.
The selected user is stored in `localStorage` and sent as an `X-User-ID`
header on every request. The backend resolves the user from the DB and
sets RLS variables in a middleware.

### Reasoning
The assignment's security requirement is about data isolation at the
infrastructure layer, not about authentication strength. JWT + refresh
tokens would take 2–3 hours of implementation time (login endpoint, token
signing, expiry, refresh logic) that would be better spent on the agent,
streaming, and document generation.

The real security boundary is the RLS policy. A correct auth mechanism
sitting in front of a broken data layer is less safe than a fake auth
sitting in front of a correct data layer.

### What would change in production
- Replace `X-User-ID` with JWT issued at login, verified on every request.
- Add refresh token rotation with short-lived access tokens (15 min).
- Store sessions server-side (Postgres or Redis) for revocation support.
- HTTPS enforced everywhere — `X-User-ID` as-is is trivially spoofable
  without TLS.

---

## 4. Agent: LangChain with scoped tools

### Decision
LangChain agent with four tools:
- `sql_query` — executes read-only SQL on a connection that already has RLS active
- `python_exec` — runs generated code in an isolated subprocess
- `generate_pdf / generate_excel / generate_word` — produce real documents

The agent never receives tenancy logic as a prompt instruction. It simply
cannot reach data outside its session scope.

### Reasoning
Prompt-level isolation ("only return data for company X") is fragile by
definition — it can be overridden by a sufficiently crafted user message or
a model that ignores instructions. Infrastructure-level isolation cannot.

### How the scoped connection reaches the tools

The background task opens a dedicated connection for the run and passes it
explicitly to each tool as a constructor dependency. The tool itself has no
knowledge of tenancy — it receives a connection that is already scoped and
simply uses it.

```python
# agent/agent.py
async def execute_agent(run_id: str, user: User, prompt: str):
    async with db.scoped_connection(user) as conn:
        sql_tool = SQLQueryTool(conn=conn)
        python_tool = PythonExecTool(company_id=user.company_id)
        
        agent = build_agent(tools=[sql_tool, python_tool])
        await agent.run(prompt)
```

`scoped_connection` is a context manager that opens a dedicated connection,
sets `SET LOCAL` inside a transaction, yields it for the duration of the run,
and closes it on exit:

```python
# db/connection.py
@asynccontextmanager
async def scoped_connection(user: User):
    conn = await db.acquire()
    await conn.execute("BEGIN")
    await conn.execute(
        "SET LOCAL app.current_company_id = :cid", {"cid": user.company_id}
    )
    await conn.execute(
        "SET LOCAL app.current_access_scope = :scope", {"scope": user.access_scope}
    )
    await conn.execute(
        "SET LOCAL app.current_role = :role", {"role": user.role}
    )
    try:
        yield conn
    finally:
        await conn.execute("COMMIT")  # SET LOCAL dies here
        await conn.close()
```

This design has two important properties:

**The connection is dedicated.** Each background task acquires its own
connection — it is never shared with another user's task or request. There
is no risk of one user's `SET LOCAL` leaking into another user's query.

**The tool is dumb by design.** `SQLQueryTool` does not know what company
or role it is operating for. It receives a connection and executes queries
on it. All tenancy responsibility is centralized in `scoped_connection`,
which is the only place that needs to be correct.

### Security guarantee

Even if a bug caused two tasks to share the same connection, RLS would still
hold — Postgres enforces the policy at the row level regardless of how the
query arrived. The connection isolation is a structural safeguard; RLS is
the security primitive.

### What would change in production
- Evaluate OpenAI's Code Interpreter or a dedicated sandboxed execution
  service instead of subprocess for `python_exec`.
- Add tool-level logging with `run_id` and `user_id` for every tool call,
  to support auditing and debugging.
- Rate-limit tool calls per user to prevent runaway agent loops consuming
  LLM budget.

---

## 5. Code execution: subprocess with isolated environment

### Decision
`python_exec` runs agent-generated code in a subprocess with a clean
environment — no inheritance from the parent process. The subprocess
receives only:
- `DATABASE_URL` scoped to the current user's DB role
- `COMPANY_ID`
- `USER_ROLE`
- 30-second execution timeout

### Reasoning
LangChain's default `PythonREPLTool` executes code in the main process,
giving the agent access to the full environment including credentials,
filesystem, and network. In a multi-tenant context this is unacceptable.

A subprocess with a clean env is the pragmatic middle ground: it prevents
accidental or intentional access to parent process secrets, while being
simple enough to implement and explain in a day.

### Per-role sandbox credentials
The subprocess reaches Postgres over the network as a `sandbox_<company>_<scope>`
role whose tenancy is fixed by `role_tenancy` + RLS. The catch: if every sandbox
role shared one password, code in one tenant's sandbox could compose a
connection string for another tenant's role and read across the boundary — RLS
would faithfully serve the *other* tenant's rows, because the connection truly
authenticated as that role. So each sandbox role's password is derived by HMAC
from a single `SANDBOX_SECRET` that lives only in the backend environment and is
never placed in the subprocess env. The subprocess gets a working URL for its
own role only; it has no way to derive a sibling's password. (Regression-tested
in `tests/smoke_tools.py`.)

### What would change in production
- **Docker container per execution** — each agent code run spins up a
  minimal container with no filesystem access, no network, hard CPU/RAM
  limits via cgroups. The subprocess approach still shares the host OS,
  meaning the agent code can read the host filesystem or exhaust resources
  beyond the timeout window.
- `seccomp` profile to restrict syscalls available to the subprocess.
- Network namespace isolation to prevent the subprocess from making
  outbound HTTP calls.

---

## 6. Background runs: asyncio + Postgres

### Decision
Agent runs are launched as FastAPI `BackgroundTasks` (asyncio). Run state
and output chunks are persisted in Postgres (`agent_runs`, `run_chunks`).
The frontend reconnects via SSE and replays from the last seen chunk.

### Reasoning
The requirement is that a user can navigate away and return to find the run
state intact. Asyncio background tasks satisfy this for a single-process
deployment. Postgres satisfies the persistence requirement without adding a
new service.

Redis would add TTL-based cleanup automatically but requires a fourth
container and a new connection to manage. Celery would add a broker,
worker processes, and deploy complexity. Neither is justified for a demo
with a handful of concurrent users.

### Known limitation: process restart
`BackgroundTasks` are in-memory asyncio coroutines. If the backend container
restarts while a run is active, the task dies silently but the Postgres record
remains stuck in `running` state forever — the user returns to a run that
shows as running but will never complete or fail.

For the demo this is an accepted risk. The mitigation in place is minimal:
on backend startup, a recovery routine marks any run still in `running` state
as `failed` with a `interrupted_by_restart` reason, so the UI surfaces a
clear error instead of an infinite spinner.

```python
# backend/main.py — on startup
@app.on_event("startup")
async def recover_interrupted_runs():
    db.execute("""
        UPDATE agent_runs
        SET status = 'failed', error = 'interrupted_by_restart'
        WHERE status = 'running'
    """)
```

### What would change in production
- Replace `BackgroundTasks` with a proper task queue (Celery + Redis or
  Postgres-backed queue like `pgqueue`) to support multiple worker processes,
  horizontal scaling, and true task durability across restarts.
- Add dead letter handling for failed runs with automatic retry logic.
- Cap stored chunks per run and add a cleanup job for old runs to prevent
  unbounded DB growth.

---

## 7. Streaming: Server-Sent Events (SSE)

### Decision
Real-time output is streamed from backend to frontend via SSE
(`text/event-stream`). The frontend uses the native `EventSource` API.

### Reasoning
SSE is unidirectional (server → client) and that is all we need here —
the agent sends progress and output, the client only sends new prompts via
regular POST requests. WebSockets would add bidirectional complexity
(connection management, heartbeat, reconnect logic) for no benefit in
this use case.

SSE also reconnects automatically on disconnect and supports resuming from
a `Last-Event-ID`, which pairs naturally with the chunk-based Postgres storage.

### What would change in production
- Implement `Last-Event-ID` support properly so the client resumes
  from the correct chunk after a disconnect rather than replaying from the start.
- Add backpressure handling if chunk production outpaces client consumption.

---

## 8. Chat history: PostgresChatMessageHistory

### Decision
LangChain's `PostgresChatMessageHistory` stores conversation history per
user (`session_id = user_id`). History is loaded on every agent invocation
so the agent has full context of past interactions.

### Reasoning
The requirement states that chat history must be user-specific, even within
the same company. Storing in Postgres keeps all state in one place, is
covered by RLS, and requires no additional infrastructure.

### What would change in production
- Implement history truncation or summarization for long conversations to
  avoid exceeding the model's context window.
- Add explicit history deletion endpoint to let users reset their context.

---

## 9. Document generation: real files via Python libraries

### Decision
Documents are generated as real files using:
- `reportlab` for PDF
- `openpyxl` for Excel
- `python-docx` for Word

Files are stored on disk under a path scoped to `user_id`, referenced in
the `documents` table, and served via a authenticated download endpoint.

### Reasoning
The assignment explicitly requires non-mocked documents. These libraries
produce real, openable files with actual data from the DB.

### What would change in production
- Move file storage to object storage (S3 or equivalent) instead of local
  disk — local disk does not survive container restarts or horizontal scaling.
- Add signed URLs with expiry for document downloads instead of a plain
  authenticated endpoint.
- Implement document cleanup for old or orphaned files.

---

## 10. Frontend: React (Vite + TypeScript + Tailwind)

### Decision
Single-page React app. No router, no global state manager. `useState` and
`useEffect` only. Three components: `UserSelector`, `ChatWindow`,
`RunHistory`.

### Reasoning
The frontend is deliberately minimal. The assignment's value is in the
backend — tenancy, RLS, agent, streaming. A clean, readable frontend is
better than a complex one. Vite gives fast iteration, TypeScript prevents
trivial bugs, Tailwind avoids writing custom CSS.

### What would change in production
- Add proper routing (React Router) for deep-linkable run URLs.
- Replace localStorage user state with a real auth flow.
- Add error boundaries and loading states throughout.
- Consider a data-fetching library (React Query / SWR) for run polling
  and cache invalidation.

---

## 11. Deployment: Docker Compose on Railway

### Decision
Three containers managed via Docker Compose:
- `frontend` — nginx serving the React static build
- `backend` — FastAPI + uvicorn
- `db` — PostgreSQL with a named volume for data persistence

### Reasoning
Postgres is containerized rather than using Railway's managed offering
because RLS with custom session variables (`SET LOCAL app.current_company_id`)
is a non-standard configuration. Running our own container guarantees that
the setup is identical between local development and the Railway deploy —
same Postgres version, same RLS policies, same migration scripts applied
in the same way. With a managed service there is a risk of unexpected
constraints on session-level configuration or extension availability.

The local dev and production environments are therefore identical:
`docker compose up` works the same everywhere.

### What would change in production
- Separate frontend hosting (Vercel, Cloudflare Pages) from backend for
  independent scaling and simpler deploy pipelines.
- Add a reverse proxy (nginx or Caddy) in front of the backend for TLS
  termination and rate limiting.
- Migrate to a managed Postgres service (Railway, Supabase, RDS) once
  RLS compatibility is verified — managed services provide automatic
  backups, point-in-time recovery, and connection pooling out of the box.
- Introduce environment-specific configs (dev / staging / prod) with
  secrets management (Railway secrets, Doppler, or Vault).