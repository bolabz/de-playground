# FastAPI service image — a separate deployable from the pipeline (its own lifecycle).
# Mirrors deploying the same app to Azure Container Apps / App Service.
#
# Build context: REPO ROOT (compose: `context: ..`, `dockerfile: api/Dockerfile`). The api
# now imports de_playground.contracts (WS4), so the build needs to see both api/ and
# src/de_playground/. WS7 promoted api/ to a workspace member with its own pyproject.toml;
# WS4 added one workspace dep on de_playground for the shared Pydantic models. Deps still
# come from api/pyproject.toml (no inline pinning).
FROM python:3.11-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Layer ordering for cache-friendliness: deps + minimal-source first, then app sources.
# README.md is required by hatchling because the root pyproject declares `readme = "README.md"`.
COPY pyproject.toml uv.lock README.md ./
COPY api/pyproject.toml ./api/
COPY src/de_playground ./src/de_playground/

# Install the api workspace member + its de_playground dep, into the system Python.
# de_playground's pyproject.toml is at /app/ (the root); api's is at /app/api/.
RUN uv pip install --system --no-cache . ./api/ \
 && opentelemetry-bootstrap -a install      # auto-install instrumentation for installed libs

COPY api/main.py ./api/

EXPOSE 8000
WORKDIR /app/api
# `opentelemetry-instrument` zero-code-instruments FastAPI (traces + metrics + logs) and exports
# via OTLP to OTEL_EXPORTER_OTLP_ENDPOINT (set in compose). If the collector isn't running it
# just logs harmless export warnings and still serves requests.
CMD ["opentelemetry-instrument", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
