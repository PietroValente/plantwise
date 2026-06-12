import uuid
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.runner import execute_run
from app.db.pool import execute_scoped, fetch_all_scoped, fetch_one_scoped
from app.middleware.tenant import CurrentUser
from app.models import Run, RunCreate, User

router = APIRouter()


@router.post("/runs", response_model=Run, status_code=202)
async def create_run(
    body: RunCreate, background: BackgroundTasks, user: User = CurrentUser
):
    """Start an agent run; returns immediately with run_id (Decision 6).
    The run continues server-side regardless of what the client does next."""
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    run_id = uuid.uuid4()
    await execute_scoped(
        user,
        """INSERT INTO agent_runs (run_id, user_id, company_id, prompt, status)
           VALUES ($1, $2, $3, $4, 'running')""",
        run_id, user.user_id, user.company_id, prompt,
    )
    background.add_task(execute_run, run_id, user, prompt)
    row = await fetch_one_scoped(
        user,
        """SELECT run_id, prompt, status, error, created_at, updated_at
           FROM agent_runs WHERE run_id = $1""",
        run_id,
    )
    return Run(**dict(row))


@router.get("/runs", response_model=list[Run])
async def list_runs(user: User = CurrentUser):
    rows = await fetch_all_scoped(
        user,
        """SELECT run_id, prompt, status, error, created_at, updated_at
           FROM agent_runs ORDER BY created_at DESC LIMIT 100""",
    )
    return [Run(**dict(r)) for r in rows]


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: UUID, user: User = CurrentUser):
    row = await fetch_one_scoped(
        user,
        """SELECT run_id, prompt, status, error, created_at, updated_at
           FROM agent_runs WHERE run_id = $1""",
        run_id,
    )
    if row is None:
        # Unknown id and other-user's id are indistinguishable through RLS.
        raise HTTPException(status_code=404, detail="run not found")
    return Run(**dict(row))
