"""Airflow DAG: WideWorldImporters medallion ELT — extract -> transform -> index.

THIN by design: this file only wires task ordering, schedule, and retries. All business
logic lives in the de_playground package and is *invoked* here, never defined here.

Each task shells out to the pipeline's isolated venv (baked into the image, kept separate from
Airflow's own deps — the pipeline needs SQLAlchemy 2.x plus a heavy Spark/ODBC stack, so
isolating it avoids dependency clashes). The same entrypoints you run by hand
(`python -m de_playground.*`) run here on a schedule with retries.

Runs on Airflow 3 (KubernetesExecutor on k3d): each task is its own ephemeral pod. Endpoints
come from the pod env — tasks reach SQL Server, SeaweedFS, and Elasticsearch on the host via
`host.docker.internal` (the data services stay in docker compose; Airflow runs on the cluster).
Transform runs Spark in local mode inside the task pod.
"""

from __future__ import annotations

from datetime import datetime, timedelta

try:  # Airflow 3: authoring API moved to the Task SDK
    from airflow.sdk import DAG
except ImportError:  # legacy Airflow 2.x fallback (the cluster runs 3.x; kept for portability)
    from airflow import DAG  # type: ignore[no-redef,attr-defined]

try:  # Airflow 3: BashOperator lives in the standard provider (also installable on 2.x)
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:
    from airflow.operators.bash import BashOperator  # type: ignore[no-redef]

# Pipeline runs in its own baked-in venv (de_playground installed from the wheel), so `python -m`
# resolves it directly. The PYTHONPATH below is a vestigial leftover from the volume-mounted
# compose era — /opt/de_playground/src doesn't exist in the k8s image, so it's a harmless no-op.
_RUN = "PYTHONPATH=/opt/de_playground/src /opt/pipeline-venv/bin/python -m"

default_args = {
    "owner": "de-playground",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="wwi_pipeline",
    description="WideWorldImporters medallion ELT: extract -> transform -> index",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    # backfill on demand (Airflow 3 CLI): `airflow backfill create --dag-id wwi_pipeline ...`
    catchup=False,
    max_active_runs=1,  # transforms overwrite, so never run two at once
    default_args=default_args,
    tags=["de-playground", "medallion"],
) as dag:
    extract = BashOperator(
        task_id="extract_bronze",
        bash_command=f"{_RUN} de_playground.extract",
    )
    transform = BashOperator(
        task_id="transform_silver_gold",
        bash_command=f"{_RUN} de_playground.transform",
    )
    index = BashOperator(
        task_id="index_elasticsearch",
        bash_command=f"{_RUN} de_playground.load.to_elasticsearch",
    )

    extract >> transform >> index
