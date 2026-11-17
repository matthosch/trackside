# Build context is the repository root, so the migrations can be copied in.
FROM python:3.12-slim

WORKDIR /app
COPY pipelines/pyproject.toml ./
COPY pipelines/trackside_pipelines ./trackside_pipelines
RUN pip install --no-cache-dir .
COPY db/migrations ./db/migrations

ENV MIGRATIONS_DIR=/app/db/migrations
CMD ["python", "-m", "trackside_pipelines.seed"]
