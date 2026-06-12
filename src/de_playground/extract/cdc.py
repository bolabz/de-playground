"""CDC extract: SQL Server change tables -> Bronze change feed (s3://bronze/wwi_cdc/<table>).

This is the change-data-capture counterpart to the watermark extract (pipeline.py). Where the
watermark only sees inserts/edits via LastEditedWhen, CDC captures every insert/update/delete
from SQL Server's `cdc.<instance>_CT` change tables — including deletes, which the watermark
misses entirely.

Run:  uv run python -m de_playground.extract.cdc   (or `make extract-cdc`)
Prereq: `make enable-cdc` (CDC enabled + SQL Agent running).

How it reads: we query the change table directly and project three clean change-metadata
columns plus the business columns (discovered dynamically, so we never hardcode schemas):
  * change_lsn       — __$start_lsn as a fixed-width hex string (sortable, JSON-safe watermark)
  * change_seqval    — __$seqval as hex (tiebreaker in a txn; orders update before/after)
  * change_operation — 1=delete, 2=insert, 3=update(before image), 4=update(after image)

dlt tracks the max change_lsn as state, so each run pulls only newer change rows (idempotent).
CDC captures from enablement forward — it does not backfill pre-existing rows.
"""

from __future__ import annotations

from collections.abc import Iterator

import dlt
from dlt.extract.resource import DltResource
from sqlalchemy import create_engine, text

from ..common.lake import ensure_bucket
from ..common.logging import get_logger, set_correlation_id
from ..config import settings
from .tables import WWI_TABLES, TableSpec

log = get_logger(__name__)

PIPELINE_NAME = "wwi_cdc_bronze"
DATASET_NAME = "wwi_cdc"
_INITIAL_LSN = "0" * 20  # binary(10) -> 20 hex chars; everything sorts after this


def _capture_instance(spec: TableSpec) -> str:
    # default capture instance name created by sp_cdc_enable_table
    return f"{spec.schema}_{spec.table}"


def _business_columns(engine, capture_instance: str) -> list[str]:
    """Columns of the change table minus CDC's own __$ metadata columns."""
    q = text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = 'cdc' AND TABLE_NAME = :ct "
        "AND COLUMN_NAME NOT LIKE '\\_\\_$%' ESCAPE '\\' "
        "ORDER BY ORDINAL_POSITION"
    )
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(q, {"ct": f"{capture_instance}_CT"})]


def _cdc_resource(spec: TableSpec, engine) -> DltResource:
    capture = _capture_instance(spec)
    ct = f"{capture}_CT"
    business = _business_columns(engine, capture)
    select_business = ", ".join(f"ct.[{c}]" for c in business)

    @dlt.resource(
        name=spec.resource_name,
        write_disposition="append",
        primary_key=spec.primary_key,
    )
    def _res(
        # dlt injects + tracks the watermark via this parameter default (its standard pattern).
        change_lsn=dlt.sources.incremental("change_lsn", initial_value=_INITIAL_LSN),  # noqa: B008
    ) -> Iterator[dict]:
        last = change_lsn.last_value or _INITIAL_LSN
        # `ct`/`select_business` derive from hardcoded WWI_TABLES, not user input.
        sql = text(
            f"SELECT CONVERT(CHAR(20), ct.[__$start_lsn], 2) AS change_lsn, "  # noqa: S608
            f"CONVERT(CHAR(20), ct.[__$seqval], 2) AS change_seqval, "
            f"ct.[__$operation] AS change_operation, {select_business} "
            f"FROM cdc.[{ct}] AS ct "
            f"WHERE CONVERT(CHAR(20), ct.[__$start_lsn], 2) > :last "
            f"ORDER BY ct.[__$start_lsn], ct.[__$seqval]"
        )
        with engine.connect() as conn:
            for row in conn.execute(sql, {"last": last}).mappings():
                yield dict(row)

    return _res()


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
    engine = create_engine(settings.mssql_url)
    resources = [_cdc_resource(spec, engine) for spec in WWI_TABLES]
    pipeline = build_pipeline()
    load_info = pipeline.run(resources, loader_file_format="parquet")
    log.info("cdc load complete", extra={"pipeline": PIPELINE_NAME, "load_info": str(load_info)})
    log.info(
        "cdc normalize summary",
        extra={"normalize_info": str(pipeline.last_trace.last_normalize_info)},
    )
    engine.dispose()


if __name__ == "__main__":
    run()
