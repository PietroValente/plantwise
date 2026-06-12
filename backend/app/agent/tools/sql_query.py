"""sql_query tool — read-only SQL on a connection that already carries the
caller's tenancy (Decision 3: the tool is dumb by design; it has no idea what
company or role it serves)."""

import asyncio
import json
import re

import asyncpg

MAX_ROWS = 200

# This regex is a UX gate, not the security boundary: a data-modifying CTE
# (WITH x AS (DELETE ...) SELECT ...) would pass it. What actually blocks
# writes is the run's READ ONLY transaction plus the app role's SELECT-only
# grants on tenant data.
_ALLOWED = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def make_sql_query_tool(conn: asyncpg.Connection):
    # The model may emit parallel tool calls; an asyncpg connection cannot run
    # concurrent queries, so serialize access to the run's dedicated connection.
    lock = asyncio.Lock()

    async def sql_query(query: str) -> str:
        """Run a read-only SQL query against the plant database and return the
        rows as JSON. Only SELECT/WITH statements are accepted. Results are
        capped at 200 rows — aggregate in SQL instead of fetching raw rows.

        Args:
            query: a single SELECT (or WITH ... SELECT) statement.
        """
        q = query.strip().rstrip(";")
        if ";" in q:
            return "error: multiple statements are not allowed"
        if not _ALLOWED.match(q):
            return "error: only read-only SELECT queries are allowed"
        try:
            # lock: serialize access to the run's single connection (the model
            # can emit parallel tool calls; asyncpg has no concurrent queries).
            # transaction(): a per-query savepoint, so one failed query (bad
            # SQL, read-only violation) rolls back just itself instead of
            # aborting the run's transaction and poisoning every later query.
            async with lock, conn.transaction():
                rows = await conn.fetch(q)
        except asyncpg.PostgresError as exc:
            return f"error: {exc}"
        out = [dict(r) for r in rows[:MAX_ROWS]]
        payload = json.dumps(out, default=str)
        if len(rows) > MAX_ROWS:
            payload += f'\n(note: result truncated to {MAX_ROWS} of {len(rows)} rows)'
        return payload

    return sql_query
