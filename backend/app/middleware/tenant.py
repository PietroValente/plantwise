"""Tenant gate (Decision 3: fake auth, real RLS).

Resolves the X-User-ID header into a User via the authenticate_user()
SECURITY DEFINER function, the single deliberate RLS bypass. Every scoped
query downstream gets its tenancy from this object via scoped_connection().

The native EventSource API cannot set request headers, so the SSE route may
pass the id as a ?user_id= query parameter instead — same resolution path.
"""

from fastapi import Depends, HTTPException, Query, Request

from app.db import pool
from app.models import User


async def _resolve(user_id: str | None) -> User:
    if not user_id:
        raise HTTPException(status_code=401, detail="missing X-User-ID header")
    p = await pool.raw_pool()
    row = await p.fetchrow("SELECT * FROM authenticate_user($1)", user_id)
    if row is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return User(**dict(row))


async def current_user(request: Request) -> User:
    return await _resolve(request.headers.get("X-User-ID"))


async def current_user_sse(
    request: Request, user_id: str | None = Query(default=None)
) -> User:
    return await _resolve(request.headers.get("X-User-ID") or user_id)


CurrentUser = Depends(current_user)
CurrentUserSSE = Depends(current_user_sse)
