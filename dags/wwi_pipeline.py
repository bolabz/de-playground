"""Airflow DAG: WideWorldImporters medallion ELT — extract -> transform -> index.

THIN by design: this file only wires task ordering, schedule, and retries. All business
logic lives in the de_playground package and is *invoked* here, never defined here.

Each task shells out to the pipeline's isolated venv (kept separate from Airflow's own deps,
since Airflow 2.x pins SQLAlchemy <2.0 while the pipeline wants 2.0). The same entrypoints
you run by hand (`python -m de_playground.*`) run here on a schedule with retries.

Endpoints come from the container env (service names on the `de` network): the tasks reach
SQL Server, SeaweedFS, and Elasticsearch by name. Transform runs Spark in local mode inside
the worker.
"""

from __future__ import annotations

from datetime import datetime, timedelta

try:  # Airflow 3: authoring API moved to the Task SDK
    from airflow.sdk import DAG
except ImportError:  # Airflow 2.x (compose setup, during the 5b transition)
    from airflow import DAG  # type: ignore[no-redef,attr-defined]

try:  # Airflow 3: BashOperator lives in the standard provider (also installable on 2.x)
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:
    from airflow.operators.bash import BashOperator  # type: ignore[no-redef]

# Pipeline runs in its own venv; PYTHONPATH points at the mounted source.
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
    catchup=False,  # backfill on demand: `airflow dags backfill ...`
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
