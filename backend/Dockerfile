# Build context is the REPO ROOT (see docker-compose.yml) so the image is
# self-contained: app code, migrations, and source data all baked in. No bind
# mounts needed — the image runs identically locally and on Railway.
FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/entrypoint.sh .
COPY db/migrations ./db/migrations
COPY data ./data
RUN chmod +x entrypoint.sh

EXPOSE 8000
CMD ["./entrypoint.sh"]
