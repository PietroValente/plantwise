# Deploying to Railway

The stack is plain Docker Compose (Decision 11), so any host that runs compose
works. On Railway:

1. Create a project → "Deploy from GitHub repo" → pick this repo.
2. Railway detects `docker-compose.yml` (via the Compose import) or create the
   three services manually, each pointing at its Dockerfile:
   - **db** — use the `postgres:16-alpine` image, attach a volume at
     `/var/lib/postgresql/data`, set `POSTGRES_PASSWORD` and
     `POSTGRES_DB=plantwise`.
   - **backend** — build context = repo root, dockerfile `backend/Dockerfile`
     (the image is self-contained: app code, migrations, and `data/` are baked
     in, so no bind mounts are needed anywhere). Set env vars as in
     `docker-compose.yml` (DATABASE_URL, DATABASE_ADMIN_URL, SANDBOX_DB_HOST,
     OPENAI_API_KEY), pointing hostnames at the db service's private domain.
   - **frontend** — root `frontend/`, Dockerfile build, expose port 80,
     public domain on this service only.
3. First boot runs migrations + ingestion automatically (idempotent entrypoint).

Secrets: set `OPENAI_API_KEY` and `POSTGRES_PASSWORD` as Railway service
variables; never commit `.env`.
