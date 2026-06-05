# FastAPI service image — a separate deployable from the pipeline (its own lifecycle).
# Mirrors deploying the same app to Azure Container Apps / App Service.
FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.30" \
    "elasticsearch>=8.14,<9" \
    "opentelemetry-distro" \
    "opentelemetry-exporter-otlp" \
 && opentelemetry-bootstrap -a install      # auto-install instrumentation for installed libs

COPY main.py .

EXPOSE 8000
# `opentelemetry-instrument` zero-code-instruments FastAPI (traces + metrics + logs) and exports
# via OTLP to OTEL_EXPORTER_OTLP_ENDPOINT (set in compose). If the collector isn't running it
# just logs harmless export warnings and still serves requests.
CMD ["opentelemetry-instrument", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
