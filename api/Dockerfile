# FastAPI service image — a separate deployable from the pipeline (its own lifecycle).
# Mirrors deploying the same app to Azure Container Apps / App Service.
# Post-WS7: deps come from api/pyproject.toml (workspace member), not inline pinning, so
# the deployable's deps stop drifting from the workspace's. uv resolves and installs as a
# system Python install (no venv inside the image — single-purpose container).
FROM python:3.11-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY pyproject.toml main.py ./
RUN uv pip install --system --no-cache . \
 && opentelemetry-bootstrap -a install      # auto-install instrumentation for installed libs

EXPOSE 8000
# `opentelemetry-instrument` zero-code-instruments FastAPI (traces + metrics + logs) and exports
# via OTLP to OTEL_EXPORTER_OTLP_ENDPOINT (set in compose). If the collector isn't running it
# just logs harmless export warnings and still serves requests.
CMD ["opentelemetry-instrument", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
