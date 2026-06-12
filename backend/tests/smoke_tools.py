"""Tool-level smoke tests that run inside the backend container, no LLM needed.

  docker compose exec backend python -m tests.smoke_tools

Covers: agent construction, sql_query scoping + read-only enforcement,
python_exec sandbox isolation (including adversarial SET of session vars),
and real document generation with RLS-scoped registration."""

import asyncio
import json
import uuid

from app.agent.agent import build_agent
from app.agent.tools.documents import make_document_tools
from app.agent.tools.python_exec import make_python_exec_tool
from app.agent.tools.sql_query import make_sql_query_tool
from app.db import pool
from app.models import User

C1_ADMIN = User(user_id="company_1_admin", company_id="company_1",
                email="a@x", role="admin", access_scope="energy+financial")
C1_OPERATOR = User(user_id="company_1_operator", company_id="company_1",
                   email="o@x", role="operator", access_scope="energy")

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((PASS if ok else FAIL, name))
    print(f"[{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    await pool.init_pool()

    # 1. Agent builds with all five tools.
    async with pool.scoped_connection(C1_ADMIN) as conn:
        agent = build_agent(C1_ADMIN, uuid.uuid4(), conn)
        check("create_deep_agent builds", agent is not None)

    # 2. sql_query: scoped results, only company_1 visible.
    async with pool.scoped_connection(C1_ADMIN) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")
        sql_tool = make_sql_query_tool(conn)
        out = json.loads(await sql_tool("SELECT id, company_id FROM plants ORDER BY id"))
        check("sql_query sees only own company",
              [r["id"] for r in out] == [1001, 1002], str(out))

        # 3. read-only: writes rejected by validation AND by the transaction.
        out = await sql_tool("DELETE FROM plants")
        check("sql_query rejects non-SELECT", out.startswith("error:"), out)
        out = await sql_tool("SELECT 1; DELETE FROM plants")
        check("sql_query rejects multi-statement", out.startswith("error:"), out)
        # defense-in-depth: a data-modifying CTE passes the regex but the
        # READ ONLY transaction must still block it.
        out = await sql_tool(
            "WITH x AS (DELETE FROM plants RETURNING id) SELECT count(*) FROM x"
        )
        check("read-only txn blocks data-modifying CTE", out.startswith("error:"), out)
        # the run's transaction must survive that failure (savepoint isolation):
        # a later query still works rather than hitting "transaction is aborted".
        out = json.loads(await sql_tool("SELECT count(*) AS n FROM plants"))
        check("query after a failed query still works", out[0]["n"] == 2, str(out))

        # 4. financial scope: admin sees own company's prices (2928 of the
        # 5856 total rows — the other company's 2928 are invisible).
        out = json.loads(await sql_tool("SELECT count(*) AS n FROM market_prices"))
        check("admin sees own company's financial rows", out[0]["n"] == 2928, str(out))

    # ...operator does not.
    async with pool.scoped_connection(C1_OPERATOR) as conn:
        await conn.execute("SET TRANSACTION READ ONLY")
        sql_tool = make_sql_query_tool(conn)
        out = json.loads(await sql_tool("SELECT count(*) AS n FROM market_prices"))
        check("energy-scope user sees 0 financial rows", out[0]["n"] == 0, str(out))

    # 4b. sandbox role is SELECT-only: writes rejected by Postgres grants.
    py_admin = make_python_exec_tool(C1_ADMIN)
    out = await py_admin(
        "import os, psycopg\n"
        "c = psycopg.connect(os.environ['DATABASE_URL'])\n"
        "try:\n"
        "    c.cursor().execute(\"INSERT INTO plants (id, company_id, name, unique_id) \"\n"
        "        \"VALUES (999,'company_1','x','0a4dfd25-5bc7-5405-b347-14cb30c6394c')\")\n"
        "    c.commit(); print('WROTE')\n"
        "except Exception as e: print('rejected', type(e).__name__)\n"
    )
    check("sandbox cannot write (SELECT-only grants)",
          "WROTE" not in out and "rejected" in out, out.strip())

    # 5. python_exec: sandbox sees only its company, adversarial SET is inert.
    py = make_python_exec_tool(C1_OPERATOR)
    out = await py(
        "import os, psycopg\n"
        "conn = psycopg.connect(os.environ['DATABASE_URL'])\n"
        "cur = conn.cursor()\n"
        "cur.execute(\"SET app.current_company_id='company_2'\")\n"
        "cur.execute(\"SET app.current_access_scope='energy+financial'\")\n"
        "cur.execute('SELECT id FROM plants ORDER BY id')\n"
        "print('plants:', [r[0] for r in cur.fetchall()])\n"
        "cur.execute('SELECT count(*) FROM market_prices')\n"
        "print('financial rows:', cur.fetchone()[0])\n"
    )
    check("python_exec adversarial SET still company_1 only",
          "plants: [1001, 1002]" in out and "financial rows: 0" in out, out.strip())

    # 6. python_exec: clean env — no parent secrets.
    out = await py("import os; print(sorted(k for k in os.environ if k not in "
                   "('PATH','SYSTEMROOT','HOME','LC_CTYPE','PWD','OLDPWD','SHLVL','_'))) ")
    check("python_exec env contains only the whitelisted vars",
          "OPENAI_API_KEY" not in out and "DATABASE_ADMIN_URL" not in out, out.strip())

    # 7. python_exec: timeout enforced.
    out = await py("import time; time.sleep(60)")
    check("python_exec timeout", "timeout" in out, out.strip())

    # 7b. cross-tenant breach regression: a company_1 sandbox must NOT be able
    # to reach company_2's role over the network. The old shared password is
    # rejected; the secret needed to derive a sibling's password is not in env.
    out = await py(
        "import os, psycopg\n"
        "host = os.environ['DATABASE_URL'].split('@')[1]\n"
        "for pw in ('sandbox_pw', 'sandbox_company_2_financial'):\n"
        "    try:\n"
        "        psycopg.connect(f'postgresql://sandbox_company_2_financial:{pw}@{host}', connect_timeout=5)\n"
        "        print('BREACH')\n"
        "    except Exception as e:\n"
        "        print('rejected', type(e).__name__)\n"
    )
    check("python_exec cannot reach sibling tenant role",
          "BREACH" not in out and out.count("rejected") == 2, out.strip())

    # 8. documents: real xlsx file + RLS-scoped row.
    run_id = uuid.uuid4()
    p = await pool.raw_pool()
    # the FK needs a run row; insert as the scoped user
    await pool.execute_scoped(
        C1_ADMIN,
        """INSERT INTO agent_runs (run_id, user_id, company_id, prompt, status)
           VALUES ($1, 'company_1_admin', 'company_1', 'smoke', 'running')""",
        run_id,
    )
    excel, pdf, word = make_document_tools(C1_ADMIN, run_id)
    out = json.loads(await excel("smoke.xlsx", "Data", ["plant", "kwh"],
                                 [["1001", "123.4"], ["1002", "99"]]))
    check("generate_excel returns created", out["status"] == "created", str(out))
    out2 = json.loads(await pdf("smoke.pdf", "Smoke", "Hello\n\nWorld",
                                ["a", "b"], [["1", "2"]]))
    out3 = json.loads(await word("smoke.docx", "Smoke", "Hello"))
    check("generate_pdf + word return created",
          out2["status"] == "created" and out3["status"] == "created")

    # 9. the other user cannot see those documents (RLS user boundary)
    rows = await pool.fetch_all_scoped(C1_OPERATOR, "SELECT id FROM documents")
    check("operator sees none of admin's documents", len(rows) == 0, str(rows))
    rows = await pool.fetch_all_scoped(
        C1_ADMIN, "SELECT filename FROM documents WHERE run_id = $1", run_id
    )
    check("admin sees this run's 3 documents", len(rows) == 3, str(rows))

    await pool.close_pool()
    failed = [n for s, n in results if s == FAIL]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
