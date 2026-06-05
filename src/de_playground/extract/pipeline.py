"""Phase 1 pipeline: WideWorldImporters (SQL Server) -> Bronze (Parquet on SeaweedFS).

Run:  uv run python -m de_playground.extract   (or `make extract`)

Idempotency: dlt stores the per-table high-watermark in its pipeline state, which it syncs
to the destination filesystem (the bronze bucket) as well as locally. So re-running pulls
only rows with cursor > last seen, and the primary key dedupes the boundary — running twice
with no new source data writes no new rows. State lives with the data, not in the job.
"""

from __future__ import annotations

import dlt

from ..common.lake import ensure_bucket
from ..common.logging import get_logger, set_correlation_id
from ..config import settings
from .source import wwi_resources

log = get_logger(__name__)

PIPELINE_NAME = "wwi_bronze"
DATASET_NAME = "wwi"


def build_pipeline() -> dlt.Pipeline:
    return dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination=dlt.destinations.filesystem(
            bucket_url=f"s3://{settings.bronze_bucket}",
            credentials={
                "aws_access_key_id": settings.s3_access_key,
                "aws_secret_access_key": settings.s3_secret_key,
                "endpoint_url": settings.s3_endpoint_url,
                "s3_url_style": "path",
            },
        ),
        dataset_name=DATASET_NAME,
        progress="log",
    )


def run() -> None:
    set_correlation_id()
    ensure_bucket(settings.bronze_bucket)
    pipeline = build_pipeline()
    load_info = pipeline.run(
        wwi_resources(settings.mssql_url),
        loader_file_format="parquet",
    )
    log.info(
        "extract load complete",
        extra={"pipeline": PIPELINE_NAME, "load_info": str(load_info)},
    )
    # Per-table row counts for the rows loaded in this run.
    log.info(
        "extract normalize summary",
        extra={"normalize_info": str(pipeline.last_trace.last_normalize_info)},
    )


if __name__ == "__main__":
    run()
