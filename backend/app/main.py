"""Plantwise backend entrypoint."""

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from app.config import DATABASE_ADMIN_URL
from app.db import pool
from app.db.sandbox import sync_app_role_password, sync_sandbox_passwords
from app.routes import documents, plants, runs, stream, users


async def recover_interrupted_runs() -> None:
    """A backend restart kills in-flight asyncio runs; without this they would
    sit in 'running' forever (Decision 6). Crosses all users, hence admin."""
    conn = await asyncpg.connect(DATABASE_ADMIN_URL)
    try:
        result = await conn.execute(
            """UPDATE agent_runs
               SET status = 'failed', error = 'interrupted_by_restart',
                   updated_at = now()
               WHERE status = 'running'"""
        )
        if result != "UPDATE 0":
            print(f"recovered interrupted runs: {result}")
    finally:
        await conn.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await sync_app_role_password()   # align pool role pw with env before connecting
    await sync_sandbox_passwords()   # distinct per-role creds before any run
    await pool.init_pool()
    await recover_interrupted_runs()
    yield
    await pool.close_pool()


app = FastAPI(title="Plantwise", lifespan=lifespan)

app.include_router(users.router, prefix="/api")
app.include_router(plants.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(documents.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
