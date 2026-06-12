-- 002_rls.sql — Row-Level Security policies (PLANNING.md §1.3, Decision 2)
--
-- Two kinds of identity reach these tables:
--
--   1. The backend ("plantwise_app" role). Its tenancy comes from session
--      variables set by scoped_connection() inside a transaction:
--        app.current_company_id, app.current_access_scope,
--        app.current_role, app.current_user_id
--      The session-variable branch of every policy is valid ONLY for
--      plantwise_app, so no other role can use SET to impersonate a tenant.
--
--   2. Sandbox roles used by python_exec (sandbox_*). Their tenancy comes
--      from the role_tenancy table keyed on current_user — an identity the
--      connection cannot change. Adversarial code in the sandbox can run
--      "SET app.current_company_id = 'company_2'" and it gains nothing.
--
-- current_setting(..., true) returns NULL when the variable is unset, which
-- makes every comparison false → zero rows. Unscoped connections see nothing.

-- Helper: the company the current sandbox login is bound to (NULL for others).
-- session_user, not current_user: it is the login identity, cannot be changed
-- by SET ROLE, and inside SECURITY DEFINER functions current_user would be the
-- function owner rather than the caller.
CREATE FUNCTION sandbox_company_id() RETURNS TEXT
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT company_id FROM role_tenancy WHERE rolname = session_user
$$;

CREATE FUNCTION sandbox_has_financial() RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT COALESCE(
        (SELECT has_financial FROM role_tenancy WHERE rolname = session_user),
        FALSE
    )
$$;

-- ── Company-scoped tables ───────────────────────────────────────────────────

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON companies FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true))
        OR company_id = sandbox_company_id()
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    );

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON users FOR ALL
    USING (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    );

ALTER TABLE plants ENABLE ROW LEVEL SECURITY;
ALTER TABLE plants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON plants FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true))
        OR company_id = sandbox_company_id()
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    );

ALTER TABLE elements ENABLE ROW LEVEL SECURITY;
ALTER TABLE elements FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON elements FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true))
        OR company_id = sandbox_company_id()
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    );

ALTER TABLE datasources ENABLE ROW LEVEL SECURITY;
ALTER TABLE datasources FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON datasources FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true))
        OR company_id = sandbox_company_id()
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    );

ALTER TABLE datapoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE datapoints FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON datapoints FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true))
        OR company_id = sandbox_company_id()
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
    );

-- ── Financial tables: company AND access_scope (Decision 2: scope, not role) ─

ALTER TABLE market_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_prices FORCE ROW LEVEL SECURITY;
CREATE POLICY financial_isolation ON market_prices FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true)
         AND current_setting('app.current_access_scope', true) = 'energy+financial')
        OR (company_id = sandbox_company_id() AND sandbox_has_financial())
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
        AND current_setting('app.current_access_scope', true) = 'energy+financial'
    );

ALTER TABLE monthly_costs ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_costs FORCE ROW LEVEL SECURITY;
CREATE POLICY financial_isolation ON monthly_costs FOR ALL
    USING (
        (current_user = 'plantwise_app'
         AND company_id = current_setting('app.current_company_id', true)
         AND current_setting('app.current_access_scope', true) = 'energy+financial')
        OR (company_id = sandbox_company_id() AND sandbox_has_financial())
    )
    WITH CHECK (
        current_user = 'plantwise_app'
        AND company_id = current_setting('app.current_company_id', true)
        AND current_setting('app.current_access_scope', true) = 'energy+financial'
    );

-- ── Per-user application state (user boundary, OQ-4) ────────────────────────
-- Sandbox roles receive no grants on these tables at all; the policies only
-- ever evaluate for plantwise_app.

ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON agent_runs FOR ALL
    USING (user_id = current_setting('app.current_user_id', true))
    WITH CHECK (user_id = current_setting('app.current_user_id', true));

-- run_chunks has no user_id column; visibility is inherited through
-- agent_runs, whose own RLS already filters to the current user.
ALTER TABLE run_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON run_chunks FOR ALL
    USING (run_id IN (SELECT run_id FROM agent_runs))
    WITH CHECK (run_id IN (SELECT run_id FROM agent_runs));

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON documents FOR ALL
    USING (user_id = current_setting('app.current_user_id', true))
    WITH CHECK (user_id = current_setting('app.current_user_id', true));

ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON chat_messages FOR ALL
    USING (session_id = current_setting('app.current_user_id', true))
    WITH CHECK (session_id = current_setting('app.current_user_id', true));

-- role_tenancy itself: readable by everyone (it only maps role names to
-- companies), writable by nobody but the superuser.
ALTER TABLE role_tenancy ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_tenancy FORCE ROW LEVEL SECURITY;
CREATE POLICY read_only_map ON role_tenancy FOR SELECT USING (true);
