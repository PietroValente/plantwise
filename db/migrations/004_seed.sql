-- 004_seed.sql — companies, users, and sandbox role tenancy map.
-- Values mirror data/company_*/company.json and users.csv exactly; the
-- ingestion script upserts the same rows, so re-running either is a no-op.

INSERT INTO companies (company_id, display_name) VALUES
    ('company_1', 'Company 1'),
    ('company_2', 'Company 2')
ON CONFLICT (company_id) DO UPDATE SET display_name = EXCLUDED.display_name;

INSERT INTO users (user_id, company_id, email, role, access_scope) VALUES
    ('company_1_admin',    'company_1', 'admin.company_1@example.com',    'admin',    'energy+financial'),
    ('company_1_operator', 'company_1', 'operator.company_1@example.com', 'operator', 'energy'),
    ('company_2_admin',    'company_2', 'admin.company_2@example.com',    'admin',    'energy+financial'),
    ('company_2_operator', 'company_2', 'operator.company_2@example.com', 'operator', 'energy')
ON CONFLICT (user_id) DO UPDATE
    SET email = EXCLUDED.email,
        role = EXCLUDED.role,
        access_scope = EXCLUDED.access_scope;

INSERT INTO role_tenancy (rolname, company_id, has_financial) VALUES
    ('sandbox_company_1_energy',    'company_1', FALSE),
    ('sandbox_company_1_financial', 'company_1', TRUE),
    ('sandbox_company_2_energy',    'company_2', FALSE),
    ('sandbox_company_2_financial', 'company_2', TRUE)
ON CONFLICT (rolname) DO UPDATE
    SET company_id = EXCLUDED.company_id,
        has_financial = EXCLUDED.has_financial;
