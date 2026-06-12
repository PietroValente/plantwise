"""Environment-driven settings. Defaults target local dev (Postgres in Docker
on port 5544, data/ checked out next to backend/)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Pool role: RLS applies (non-superuser, FORCE RLS). Used for all request- and
# agent-scoped queries.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://plantwise_app:plantwise_app_pw@localhost:5544/plantwise",
)

# Superuser: migrations + ingestion only (must write across tenants).
DATABASE_ADMIN_URL = os.getenv(
    "DATABASE_ADMIN_URL",
    "postgresql://postgres:devpass@localhost:5544/plantwise",
)

# plantwise_app pool role password. Authoritative source for the role's password:
# the backend sets it at startup (003_roles.sql only seeds a placeholder), so a
# value set here / in .env actually takes effect. Must match the password baked
# into DATABASE_URL above.
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD", "plantwise_app_pw")

# Host/port handed to python_exec sandboxes. Each sandbox role's password is
# derived from SANDBOX_SECRET (see app/db/sandbox.py); the secret stays in the
# backend env and is never exposed to the subprocess, so sandbox code cannot
# derive another role's password and cross tenants.
SANDBOX_DB_HOST = os.getenv("SANDBOX_DB_HOST", "localhost")
SANDBOX_DB_PORT = os.getenv("SANDBOX_DB_PORT", "5544")
SANDBOX_DB_NAME = os.getenv("SANDBOX_DB_NAME", "plantwise")
SANDBOX_SECRET = os.getenv("SANDBOX_SECRET", "dev-sandbox-secret-change-in-prod")

DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Generated documents land under DOCUMENTS_DIR/<user_id>/.
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(_BACKEND_DIR / "generated_documents")))

MIGRATIONS_DIR = Path(os.getenv("MIGRATIONS_DIR", str(_REPO_ROOT / "db" / "migrations")))

# LLM (ASSIGNMENT: GPT-5 via the provided key).
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-5")

PYTHON_EXEC_TIMEOUT_SECONDS = int(os.getenv("PYTHON_EXEC_TIMEOUT_SECONDS", "30"))
