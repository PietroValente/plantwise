"""Per-role sandbox credentials (closes the cross-tenant breach where all
sandbox roles shared one password).

Each sandbox_<company>_<scope> role gets a distinct password derived by HMAC
from SANDBOX_SECRET. The secret lives only in the backend's environment and is
NEVER placed in a python_exec subprocess env — so sandbox code, which only ever
receives its own role's connection URL, cannot derive a sibling role's password
and reach another tenant.

Passwords are applied to the live roles at backend startup (the backend has the
admin connection); the placeholder in 003_roles.sql is overwritten there."""

import hashlib
import hmac
import re

import asyncpg

from app.config import APP_DB_PASSWORD, DATABASE_ADMIN_URL, SANDBOX_SECRET

_ROLE_RE = re.compile(r"^sandbox_[a-z0-9_]+$")


async def sync_app_role_password() -> None:
    """Align the plantwise_app role's password with APP_DB_PASSWORD (from env),
    so .env is the single source of truth rather than the SQL placeholder. Runs
    on the admin connection before the pool is created. Idempotent."""
    conn = await asyncpg.connect(DATABASE_ADMIN_URL)
    try:
        escaped = APP_DB_PASSWORD.replace("'", "''")
        await conn.execute(f"ALTER ROLE plantwise_app WITH PASSWORD '{escaped}'")
    finally:
        await conn.close()


def derive_password(rolname: str) -> str:
    """Deterministic per-role password. Same inputs → same password, so the
    startup sync and python_exec independently agree without storing anything."""
    return hmac.new(SANDBOX_SECRET.encode(), rolname.encode(), hashlib.sha256).hexdigest()[:32]


async def sync_sandbox_passwords() -> None:
    """Set each sandbox role's password to its derived value. Idempotent."""
    conn = await asyncpg.connect(DATABASE_ADMIN_URL)
    try:
        rows = await conn.fetch("SELECT rolname FROM role_tenancy")
        for row in rows:
            rolname = row["rolname"]
            if not _ROLE_RE.match(rolname):  # defends the f-string DDL below
                continue
            pw = derive_password(rolname)
            # rolname is validated; pw is hex — neither can break out of the DDL.
            await conn.execute(f"ALTER ROLE {rolname} WITH PASSWORD '{pw}'")
    finally:
        await conn.close()
