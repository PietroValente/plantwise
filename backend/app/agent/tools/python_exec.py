"""python_exec tool — agent-generated code in a subprocess with a clean
environment (Decision 4).

The subprocess inherits nothing from the parent. It receives exactly:
  DATABASE_URL — a sandbox role bound to the caller's company and scope.
                 The role's tenancy is anchored in Postgres (role_tenancy +
                 RLS keyed on session_user), so even adversarial code that
                 runs SET app.current_company_id='other' gets nothing.
  COMPANY_ID, USER_ROLE — informational, not security inputs.
  A 30-second timeout and a throwaway working directory.
"""

import asyncio
import os
import sys
import tempfile

from app.config import (
    PYTHON_EXEC_TIMEOUT_SECONDS,
    SANDBOX_DB_HOST,
    SANDBOX_DB_NAME,
    SANDBOX_DB_PORT,
)
from app.db.sandbox import derive_password
from app.models import User

MAX_OUTPUT = 20_000


def sandbox_database_url(user: User) -> str:
    scope = "financial" if user.access_scope == "energy+financial" else "energy"
    role = f"sandbox_{user.company_id}_{scope}"
    # Only this role's password is derived and handed over. The secret needed to
    # derive any other role's password is not in the subprocess env.
    return (
        f"postgresql://{role}:{derive_password(role)}"
        f"@{SANDBOX_DB_HOST}:{SANDBOX_DB_PORT}/{SANDBOX_DB_NAME}"
    )


def make_python_exec_tool(user: User):
    async def python_exec(code: str) -> str:
        """Execute Python code in an isolated sandbox and return its stdout and
        stderr. Use this for analysis that is awkward in SQL (statistics,
        pandas transformations, complex aggregations).

        Available libraries: pandas, psycopg (v3), numpy, openpyxl.
        The environment variable DATABASE_URL holds a read-only connection
        string to the plant database — e.g.
        `pd.read_sql(query, psycopg.connect(os.environ["DATABASE_URL"]))`.
        The code runs with a 30-second timeout; print() what you want back.

        Args:
            code: the Python source to execute.
        """
        with tempfile.TemporaryDirectory(prefix="plantwise_exec_") as workdir:
            script = os.path.join(workdir, "script.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write(code)
            env = {
                # Minimal PATH so the interpreter itself works; no parent env.
                "PATH": os.environ.get("PATH", ""),
                "DATABASE_URL": sandbox_database_url(user),
                "COMPANY_ID": user.company_id,
                "USER_ROLE": user.role,
                "HOME": workdir,
            }
            if sys.platform == "win32":  # CPython needs it on Windows dev hosts
                env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script,
                cwd=workdir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=PYTHON_EXEC_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"error: execution exceeded {PYTHON_EXEC_TIMEOUT_SECONDS}s timeout"

        out = stdout.decode(errors="replace")[:MAX_OUTPUT]
        err = stderr.decode(errors="replace")[:MAX_OUTPUT]
        result = out
        if err:
            result += f"\n--- stderr ---\n{err}"
        if proc.returncode != 0:
            result += f"\n(exit code {proc.returncode})"
        return result or "(no output)"

    return python_exec
