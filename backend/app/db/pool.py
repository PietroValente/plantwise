"""Connection pool (plantwise_app role) and the scoped_connection context
manager — the single place tenancy is attached to a connection (Decision 3).

Every connection handed out by scoped_connection() is inside a transaction
with the four RLS session variables set via set_config(..., is_local=true),
so they die on COMMIT/ROLLBACK and can never leak across pool checkouts."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from app.config import DATABASE_URL
from app.models import User

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def scoped_connection(user: User) -> AsyncIterator[asyncpg.Connection]:
    """Yield a dedicated connection scoped to `user` for the duration of the
    block. The tools receiving it have no tenancy knowledge of their own."""
    assert _pool is not None, "pool not initialized"
    async with _pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(
                """SELECT set_config('app.current_company_id', $1, true),
                          set_config('app.current_access_scope', $2, true),
                          set_config('app.current_role', $3, true),
                          set_config('app.current_user_id', $4, true)""",
                user.company_id, user.access_scope, user.role, user.user_id,
            )
            yield conn
        except BaseException:
            await tx.rollback()
            raise
        else:
            await tx.commit()


async def fetch_one_scoped(user: User, query: str, *args):
    async with scoped_connection(user) as conn:
        return await conn.fetchrow(query, *args)


async def fetch_all_scoped(user: User, query: str, *args):
    async with scoped_connection(user) as conn:
        return await conn.fetch(query, *args)


async def execute_scoped(user: User, query: str, *args) -> str:
    async with scoped_connection(user) as conn:
        return await conn.execute(query, *args)


async def raw_pool() -> asyncpg.Pool:
    assert _pool is not None, "pool not initialized"
    return _pool
