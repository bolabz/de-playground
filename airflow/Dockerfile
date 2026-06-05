# Airflow image for the control plane. Airflow's own environment stays pristine; the pipeline
# gets an ISOLATED venv (/opt/pipeline-venv) so its deps (SQLAlchemy 2.0, dlt, pyspark, ...)
# never collide with Airflow's (which pins SQLAlchemy <2.0). The DAG's BashOperators call the
# pipeline venv's python directly.
#
# Pinned 2.11.1 (current 2.x as of 2026) for the classic LocalExecutor + `airflow users create`
# pattern; Airflow 3.x changed the CLI/compose/auth significantly.
FROM apache/airflow:2.11.1-python3.11

USER root

# System deps for the pipeline: JDK 17 (PySpark, local mode) + MS ODBC 18 (pyodbc -> SQL Server).
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

# Isolated pipeline venv (kept out of Airflow's site-packages on purpose).
RUN python -m venv /opt/pipeline-venv \
    && /opt/pipeline-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/pipeline-venv/bin/pip install --no-cache-dir \
        "dlt[sql_database,s3,parquet]>=1.0" \
        "sqlalchemy>=2.0" \
        pyodbc \
        "pydantic-settings>=2.0" \
        boto3 \
        "deltalake>=0.18" \
        "pyarrow>=16.0" \
        "pyspark==3.5.8" \
        "delta-spark==3.2.1" \
        "elasticsearch>=8.14,<9"

USER airflow
