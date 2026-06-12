"""Background run executor (Decisions 3, 6).

execute_run() is launched as a FastAPI BackgroundTask. It opens ONE dedicated
scoped connection for the data tools (read-only for the whole run) and writes
run state, chunks, and chat history through separate short scoped
transactions so they commit — and become visible to SSE readers — immediately.
"""

import json
import traceback
import uuid

from app.agent.agent import build_agent
from app.db.pool import execute_scoped, fetch_all_scoped, scoped_connection
from app.models import User

TOKEN_FLUSH_CHARS = 120
TRUNCATE_TOOL_IO = 1_500
HISTORY_MESSAGES = 20


class ChunkWriter:
    """Monotonic per-run chunk appender; seq doubles as the SSE event id."""

    def __init__(self, user: User, run_id: uuid.UUID):
        self.user = user
        self.run_id = run_id
        self.seq = 0
        self._token_buf: list[str] = []

    async def write(self, chunk_type: str, content: str) -> None:
        await self.flush_tokens()
        await self._insert(chunk_type, content)

    async def token(self, text: str) -> None:
        self._token_buf.append(text)
        if sum(len(t) for t in self._token_buf) >= TOKEN_FLUSH_CHARS:
            await self.flush_tokens()

    async def flush_tokens(self) -> None:
        if self._token_buf:
            text = "".join(self._token_buf)
            self._token_buf = []
            await self._insert("token", text)

    async def _insert(self, chunk_type: str, content: str) -> None:
        self.seq += 1
        await execute_scoped(
            self.user,
            """INSERT INTO run_chunks (run_id, seq, chunk_type, content)
               VALUES ($1, $2, $3, $4)""",
            self.run_id, self.seq, chunk_type, content,
        )


async def _set_status(user: User, run_id: uuid.UUID, status: str,
                      error: str | None = None) -> None:
    await execute_scoped(
        user,
        """UPDATE agent_runs SET status = $2, error = $3, updated_at = now()
           WHERE run_id = $1""",
        run_id, status, error,
    )


async def _load_history(user: User) -> list[dict]:
    rows = await fetch_all_scoped(
        user,
        f"""SELECT msg_role, content FROM (
                SELECT id, msg_role, content FROM chat_messages
                ORDER BY id DESC LIMIT {HISTORY_MESSAGES}
            ) t ORDER BY id""",
    )
    role_map = {"human": "user", "ai": "assistant"}
    return [{"role": role_map[r["msg_role"]], "content": r["content"]} for r in rows]


async def _save_history(user: User, prompt: str, answer: str) -> None:
    await execute_scoped(
        user,
        """INSERT INTO chat_messages (session_id, msg_role, content)
           VALUES ($1, 'human', $2), ($1, 'ai', $3)""",
        user.user_id, prompt, answer,
    )


def _truncate(value: object, limit: int = TRUNCATE_TOOL_IO) -> str:
    s = str(value)
    return s if len(s) <= limit else s[:limit] + f"… (+{len(s) - limit} chars)"


async def execute_run(run_id: uuid.UUID, user: User, prompt: str) -> None:
    writer = ChunkWriter(user, run_id)
    final_answer = ""
    try:
        history = await _load_history(user)
        async with scoped_connection(user) as conn:
            # The agent's data connection cannot write, period.
            await conn.execute("SET TRANSACTION READ ONLY")
            agent = build_agent(user, run_id, conn)
            messages = history + [{"role": "user", "content": prompt}]

            async for event in agent.astream_events({"messages": messages}):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    text = event["data"]["chunk"].content
                    if isinstance(text, str) and text:
                        await writer.token(text)
                elif kind == "on_chat_model_end":
                    msg = event["data"]["output"]
                    content = msg.content if isinstance(msg.content, str) else ""
                    if content and not getattr(msg, "tool_calls", None):
                        final_answer = content
                elif kind == "on_tool_start":
                    await writer.write("tool_start", json.dumps({
                        "tool": event["name"],
                        "input": _truncate(event["data"].get("input", "")),
                    }))
                elif kind == "on_tool_end":
                    await writer.write("tool_end", json.dumps({
                        "tool": event["name"],
                        "output": _truncate(event["data"].get("output", "")),
                    }))

        await writer.flush_tokens()
        await writer.write("final", final_answer)
        await _save_history(user, prompt, final_answer)
        await _set_status(user, run_id, "completed")
        await writer.write("done", "")
    except Exception as exc:  # noqa: BLE001 — background task boundary
        detail = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        try:
            await writer.flush_tokens()
            await writer.write("error", detail)
            await _set_status(user, run_id, "failed", detail)
            await writer.write("done", "")
        except Exception:  # noqa: BLE001 — best-effort error reporting
            traceback.print_exc()
