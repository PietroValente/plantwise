#!/bin/sh
# Migrate, ingest (both idempotent), then serve.
set -e
python -m app.db.migrate
python -m app.ingestion.ingest
# "::" binds IPv6 + IPv4 — Railway's private network is IPv6-only.
exec uvicorn app.main:app --host :: --port 8000
