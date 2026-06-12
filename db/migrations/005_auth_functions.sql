-- 005_auth_functions.sql — the two deliberate RLS bypasses for fake auth.
--
-- The tenant middleware must resolve an X-User-ID into (company, scope, role)
-- BEFORE any session variable is set — but the users table is itself behind
-- RLS. These SECURITY DEFINER functions are the explicit, auditable gate that
-- breaks that cycle. They are the only RLS bypass the app role gets, and they
-- expose exactly what a login screen would: who exists, and the claims of the
-- user being resolved (Decision 3: fake auth; the real boundary is RLS).

CREATE FUNCTION authenticate_user(p_user_id TEXT)
RETURNS TABLE (user_id TEXT, company_id TEXT, email TEXT, role TEXT, access_scope TEXT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT u.user_id, u.company_id, u.email, u.role, u.access_scope
    FROM users u WHERE u.user_id = p_user_id
$$;

-- Backs the user-selector dropdown (the "login page" of the fake auth flow).
CREATE FUNCTION list_login_users()
RETURNS TABLE (user_id TEXT, company_id TEXT, company_name TEXT, email TEXT,
               role TEXT, access_scope TEXT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT u.user_id, u.company_id, c.display_name, u.email, u.role, u.access_scope
    FROM users u JOIN companies c ON c.company_id = u.company_id
    ORDER BY u.company_id, u.role
$$;

REVOKE ALL ON FUNCTION authenticate_user(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_login_users() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION authenticate_user(TEXT) TO plantwise_app;
GRANT EXECUTE ON FUNCTION list_login_users() TO plantwise_app;
