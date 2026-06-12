#!/bin/sh
# Migrate, ingest (both idempotent), then serve.
set -e
python -m app.db.migrate
python -m app.ingestion.ingest
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
