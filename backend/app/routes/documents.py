from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db.pool import fetch_all_scoped, fetch_one_scoped
from app.middleware.tenant import CurrentUser, CurrentUserSSE
from app.models import Document, User

router = APIRouter()


@router.get("/documents", response_model=list[Document])
async def list_documents(user: User = CurrentUser):
    rows = await fetch_all_scoped(
        user,
        """SELECT id, run_id, filename, doc_type, created_at
           FROM documents ORDER BY created_at DESC LIMIT 100""",
    )
    return [Document(**dict(r)) for r in rows]


@router.get("/documents/{doc_id}/download")
async def download_document(doc_id: UUID, user: User = CurrentUserSSE):
    # CurrentUserSSE: plain <a> links cannot set headers, so ?user_id= is
    # accepted here like on the SSE route — same fake-auth surface.
    row = await fetch_one_scoped(
        user, "SELECT filename, path FROM documents WHERE id = $1", doc_id
    )
    if row is None:
        # RLS: another user's document id is simply not found.
        raise HTTPException(status_code=404, detail="document not found")
    path = Path(row["path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="file no longer on disk")
    return FileResponse(path, filename=row["filename"])
