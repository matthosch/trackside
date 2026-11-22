# Build context is the repository root, so the runbooks can be copied in.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 agent
WORKDIR /app
COPY agent/pyproject.toml ./
COPY agent/trackside_agent ./trackside_agent
RUN pip install --no-cache-dir .
COPY docs/runbooks ./docs/runbooks

RUN mkdir /outbox && chown agent /outbox
USER agent
EXPOSE 8090
CMD ["trackside-agent"]
