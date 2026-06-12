-- 003_roles.sql — database roles and grants (Decision 2/4)
--
-- plantwise_app — the backend's pool role. Non-superuser, does not own the
--   tables, and FORCE ROW LEVEL SECURITY is on, so RLS applies to it always.
--   The password below is a PLACEHOLDER: the backend rewrites it at startup to
--   APP_DB_PASSWORD (from .env), so the environment is the source of truth.
--
-- sandbox_<company>_<scope> — login roles handed to python_exec subprocesses.
--   SELECT-only on tenant data; their tenancy is anchored in role_tenancy
--   (see 002_rls.sql), not in session variables they could overwrite.
--
-- The passwords below are PLACEHOLDERS. At startup the backend rewrites each
-- sandbox role's password to a distinct value derived from SANDBOX_SECRET
-- (app/db/sandbox.py). This is what prevents sandbox code from connecting as a
-- different tenant's role — a single shared password would let it cross tenants
-- regardless of RLS. plantwise_app keeps its static password (it is the trusted
-- pool role and never reachable from sandboxed code).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'plantwise_app') THEN
        CREATE ROLE plantwise_app LOGIN PASSWORD 'plantwise_app_pw';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sandbox_company_1_energy') THEN
        CREATE ROLE sandbox_company_1_energy LOGIN PASSWORD 'sandbox_pw';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sandbox_company_1_financial') THEN
        CREATE ROLE sandbox_company_1_financial LOGIN PASSWORD 'sandbox_pw';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sandbox_company_2_energy') THEN
        CREATE ROLE sandbox_company_2_energy LOGIN PASSWORD 'sandbox_pw';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sandbox_company_2_financial') THEN
        CREATE ROLE sandbox_company_2_financial LOGIN PASSWORD 'sandbox_pw';
    END IF;
END
$$;

-- ── Backend role grants ──────────────────────────────────────────────────────
GRANT SELECT ON companies, users, plants, elements, datasources, datapoints,
                market_prices, monthly_costs, role_tenancy TO plantwise_app;
GRANT SELECT, INSERT, UPDATE ON agent_runs, run_chunks, documents, chat_messages
    TO plantwise_app;
GRANT USAGE ON SEQUENCE chat_messages_id_seq TO plantwise_app;

-- ── Sandbox role grants: tenant data only, read only ────────────────────────
GRANT SELECT ON companies, plants, elements, datasources, datapoints,
                market_prices, monthly_costs, role_tenancy
    TO sandbox_company_1_energy, sandbox_company_1_financial,
       sandbox_company_2_energy, sandbox_company_2_financial;
-- No grants on users, agent_runs, run_chunks, documents, chat_messages:
-- sandbox code has no reason to see them, so it cannot.
