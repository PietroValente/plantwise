# Database migrations

Plain SQL files applied in lexicographic order by `backend/app/db/migrate.py`
(also run automatically by the backend container entrypoint). Applied files are
tracked in `schema_migrations`; each file runs at most once.

| File | Contents |
|---|---|
| `001_schema.sql` | All tables (tenant data, financial, per-user app state, `role_tenancy`) |
| `002_rls.sql` | `ENABLE`/`FORCE ROW LEVEL SECURITY` + policies for every table |
| `003_roles.sql` | `plantwise_app` pool role, `sandbox_*` roles for `python_exec`, grants |
| `004_seed.sql` | Companies, users, sandbox tenancy map (idempotent upserts) |

Apply manually against a running Postgres:

```bash
python -m app.db.migrate          # from backend/, uses DATABASE_ADMIN_URL
```

The two identities and how RLS binds them:

- **`plantwise_app`** — tenancy from session variables (`app.current_company_id`,
  `app.current_access_scope`, `app.current_role`, `app.current_user_id`) set by
  `scoped_connection()` inside a transaction. The session-variable branch of each
  policy applies only when `current_user = 'plantwise_app'`.
- **`sandbox_*`** — tenancy from the `role_tenancy` table keyed on `current_user`.
  Setting session variables from sandbox code changes nothing.
