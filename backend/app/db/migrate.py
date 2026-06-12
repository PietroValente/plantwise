"""Apply db/migrations/*.sql in order, tracking applied files in
schema_migrations. Runs as the admin role; safe to run on every boot."""

import asyncio
import sys

import asyncpg

from app.config import DATABASE_ADMIN_URL, MIGRATIONS_DIR


async def _connect_with_retry() -> asyncpg.Connection:
    # On platforms without compose-style healthcheck ordering (e.g. Railway)
    # the db may still be starting when this runs.
    for attempt in range(30):
        try:
            return await asyncpg.connect(DATABASE_ADMIN_URL)
        except (OSError, asyncpg.PostgresError) as exc:
            print(f"db not ready (attempt {attempt + 1}/30): {exc!r}", file=sys.stderr)
            await asyncio.sleep(2)
    return await asyncpg.connect(DATABASE_ADMIN_URL)


async def migrate() -> None:
    conn = await _connect_with_retry()
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            r["filename"]
            for r in await conn.fetch("SELECT filename FROM schema_migrations")
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)", path.name
                )
            print(f"applied {path.name}")
        print("migrations up to date")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except Exception as exc:  # noqa: BLE001 — entrypoint surface
        print(f"migration failed: {exc!r}", file=sys.stderr)
        sys.exit(1)
