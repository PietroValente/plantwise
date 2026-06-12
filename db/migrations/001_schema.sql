-- 001_schema.sql — Plantwise application schema (PLANNING.md §1.2)
-- Applied by the migration runner as the postgres superuser.

-- ── Tenant data ────────────────────────────────────────────────────────────

CREATE TABLE companies (
    company_id   TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);

CREATE TABLE users (
    user_id      TEXT PRIMARY KEY,
    company_id   TEXT NOT NULL REFERENCES companies(company_id),
    email        TEXT NOT NULL UNIQUE,
    role         TEXT NOT NULL CHECK (role IN ('admin', 'operator')),
    access_scope TEXT NOT NULL CHECK (access_scope IN ('energy', 'energy+financial'))
);

CREATE TABLE plants (
    id                 INTEGER PRIMARY KEY,
    company_id         TEXT NOT NULL REFERENCES companies(company_id),
    name               TEXT NOT NULL,
    unique_id          UUID NOT NULL,
    nominal_power_kw   NUMERIC,
    region             TEXT,
    commissioning_date DATE
);

CREATE TABLE elements (
    id          INTEGER PRIMARY KEY,
    plant_id    INTEGER NOT NULL REFERENCES plants(id),
    company_id  TEXT NOT NULL REFERENCES companies(company_id),
    unique_id   UUID NOT NULL,
    name        TEXT NOT NULL,
    type        INTEGER NOT NULL,
    type_string TEXT NOT NULL
);

CREATE TABLE datasources (
    id               INTEGER PRIMARY KEY,
    element_id       INTEGER NOT NULL REFERENCES elements(id),
    plant_id         INTEGER NOT NULL REFERENCES plants(id),
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    name             TEXT NOT NULL,
    units            TEXT NOT NULL,
    aggregation_type TEXT NOT NULL CHECK (aggregation_type IN ('sum', 'average'))
);

-- The (datasource_id, ts) primary key doubles as the composite index that
-- serves the agent's range queries; a separate DESC index would be redundant.
CREATE TABLE datapoints (
    datasource_id INTEGER NOT NULL REFERENCES datasources(id),
    company_id    TEXT NOT NULL REFERENCES companies(company_id),
    ts            TIMESTAMPTZ NOT NULL,
    value         DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (datasource_id, ts)
);

-- ── Financial data (gated by access_scope, see 002_rls.sql) ────────────────

CREATE TABLE market_prices (
    company_id  TEXT NOT NULL REFERENCES companies(company_id),
    zone        TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    eur_per_mwh NUMERIC NOT NULL,
    PRIMARY KEY (company_id, zone, ts)
);

CREATE TABLE monthly_costs (
    id         BIGSERIAL PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    plant_id   INTEGER NOT NULL REFERENCES plants(id),
    year       INTEGER NOT NULL,
    month      INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    category   TEXT NOT NULL,
    amount_eur NUMERIC NOT NULL,
    notes      TEXT,
    UNIQUE (company_id, plant_id, year, month, category)
);

-- ── Per-user application state ──────────────────────────────────────────────

CREATE TABLE agent_runs (
    run_id     UUID PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    prompt     TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    error      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_runs_user ON agent_runs (user_id, created_at DESC);

CREATE TABLE run_chunks (
    run_id     UUID NOT NULL REFERENCES agent_runs(run_id),
    seq        INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE documents (
    id         UUID PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    run_id     UUID REFERENCES agent_runs(run_id),
    filename   TEXT NOT NULL,
    doc_type   TEXT NOT NULL CHECK (doc_type IN ('pdf', 'xlsx', 'docx')),
    path       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_user ON documents (user_id, created_at DESC);

-- Minimal equivalent of LangChain's PostgresChatMessageHistory (Decision 8),
-- implemented over the scoped connection so RLS covers it like everything else.
-- session_id = user_id; messages are replayed into the agent on each run.
CREATE TABLE chat_messages (
    id         BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES users(user_id),
    msg_role   TEXT NOT NULL CHECK (msg_role IN ('human', 'ai')),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_chat_messages_session ON chat_messages (session_id, id);

-- ── Sandbox role tenancy map ────────────────────────────────────────────────
-- Maps a Postgres role name to the tenant it is allowed to read. This is what
-- anchors python_exec isolation to the DB identity itself: code running in the
-- sandbox connects as one of these roles and cannot escape its row by setting
-- session variables (see 002_rls.sql).
CREATE TABLE role_tenancy (
    rolname       TEXT PRIMARY KEY,
    company_id    TEXT NOT NULL REFERENCES companies(company_id),
    has_financial BOOLEAN NOT NULL DEFAULT FALSE
);
