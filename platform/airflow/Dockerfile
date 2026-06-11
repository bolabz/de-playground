# Airflow 3 image for the k3d cluster (Phase 5b) — replaces the EOL Airflow 2.x compose image.
#
# Same isolation pattern as before: Airflow's own environment stays pristine; the pipeline
# lives in /opt/pipeline-venv. ONE difference from the compose image: the de_playground code
# is BAKED IN (installed from the wheel) instead of volume-mounted — on Kubernetes, task pods
# can't see your working tree, so code ships as an artifact. Rebuild + repush on code change:
#   make airflow3-release   (build -> push to the k3d registry -> bump tags -> tofu apply; Phase 5c)
#
# Build from the REPO ROOT (needs dist/):  docker build -f platform/airflow/Dockerfile .
# Image is pushed to the k3d registry (Phase 5c), not imported; the chart pulls it by git-SHA tag.
FROM apache/airflow:3.1.7

USER airflow
# Amazon provider — for remote task logging to SeaweedFS (S3). Installed into AIRFLOW's env
# (not the pipeline venv); constrained to this Airflow release so deps stay compatible.
RUN PYV="$(python -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')" \
    && pip install --no-cache-dir "apache-airflow-providers-amazon" \
       --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.1.7/constraints-${PYV}.txt"

USER root

# System deps for the pipeline: JDK 17 (PySpark local-mode in task pods) + MS ODBC 18 (pyodbc).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-17-jdk-headless curl gnupg apt-transport-https ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Isolated pipeline venv, with the de_playground wheel installed (pulls its base deps),
# plus the process/serve extras the DAG tasks need.
COPY dist/de_playground-0.1.0-py3-none-any.whl /tmp/
RUN python -m venv /opt/pipeline-venv \
    && /opt/pipeline-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/pipeline-venv/bin/pip install --no-cache-dir \
        "/tmp/de_playground-0.1.0-py3-none-any.whl" \
        "pyspark==3.5.8" \
        "delta-spark==3.2.1" \
        "elasticsearch>=8.14,<9" \
    && rm /tmp/de_playground-0.1.0-py3-none-any.whl

USER airflow
