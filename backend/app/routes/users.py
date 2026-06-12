from fastapi import APIRouter

from app.db import pool
from app.middleware.tenant import CurrentUser
from app.models import LoginUser, User

router = APIRouter()


@router.get("/users", response_model=list[LoginUser])
async def list_users():
    """The fake-login user selector. Unauthenticated by design — this IS the
    login page (Decision 3)."""
    p = await pool.raw_pool()
    rows = await p.fetch("SELECT * FROM list_login_users()")
    return [LoginUser(**dict(r)) for r in rows]


@router.get("/me", response_model=User)
async def me(user: User = CurrentUser):
    return user
