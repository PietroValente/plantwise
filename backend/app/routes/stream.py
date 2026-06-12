"""SSE streaming of run chunks (Decision 7).

Chunks live in Postgres (run_chunks); this generator replays everything after
Last-Event-ID (the chunk seq) and then tails the table until a 'done' chunk
arrives. Reconnects resume exactly where they left off — including for runs
that completed while the client was away.

Native EventSource cannot set headers, so the tenant gate also accepts
?user_id= here (see middleware/tenant.py)."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.db.pool import fetch_all_scoped, fetch_one_scoped
from app.middleware.tenant import CurrentUserSSE
from app.models import User

router = APIRouter()

POLL_INTERVAL_SECONDS = 0.3


def _format_event(seq: int, chunk_type: str, content: str) -> str:
    data = content.replace("\r", "")
    lines = "".join(f"data: {line}\n" for line in data.split("\n"))
    return f"id: {seq}\nevent: {chunk_type}\n{lines}\n"


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: UUID,
    user: User = CurrentUserSSE,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    run = await fetch_one_scoped(
        user, "SELECT status FROM agent_runs WHERE run_id = $1", run_id
    )
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    try:
        start_seq = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        start_seq = 0

    async def generate():
        seen = start_seq
        while True:
            rows = await fetch_all_scoped(
                user,
                """SELECT seq, chunk_type, content FROM run_chunks
                   WHERE run_id = $1 AND seq > $2 ORDER BY seq""",
                run_id, seen,
            )
            done = False
            for row in rows:
                seen = row["seq"]
                yield _format_event(row["seq"], row["chunk_type"], row["content"])
                if row["chunk_type"] == "done":
                    done = True
            if done:
                return
            # A run interrupted by restart never writes 'done'; stop on status.
            status_row = await fetch_one_scoped(
                user, "SELECT status, error FROM agent_runs WHERE run_id = $1", run_id
            )
            if status_row and status_row["status"] != "running":
                rows = await fetch_all_scoped(
                    user,
                    """SELECT seq, chunk_type, content FROM run_chunks
                       WHERE run_id = $1 AND seq > $2 ORDER BY seq""",
                    run_id, seen,
                )
                for row in rows:
                    seen = row["seq"]
                    yield _format_event(row["seq"], row["chunk_type"], row["content"])
                if status_row["status"] == "failed" and not any(
                    r["chunk_type"] == "done" for r in rows
                ):
                    yield _format_event(seen + 1, "error", status_row["error"] or "failed")
                    yield _format_event(seen + 2, "done", "")
                return
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
