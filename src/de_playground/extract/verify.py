"""Verify Phase 1: count rows that landed in Bronze, and compare to the SQL Server source.

Run:  uv run python -m de_playground.extract.verify   (or `make counts`)
      uv run python -m de_playground.extract.verify --json   (machine-readable)

Reads the Parquet directly from SeaweedFS (no Spark needed) via pyarrow's S3 filesystem,
then counts the source tables over ODBC for a side-by-side check. On a clean first load the
counts match exactly. After incremental re-runs Bronze may be >= source, because Bronze is
append-only raw history (updated rows land as new versions) — dedup is Silver's job.
"""

from __future__ import annotations

import argparse
import os

import pyarrow.dataset as ds
from sqlalchemy import create_engine, text

from ..common.lake import pyarrow_s3
from ..config import settings
from .tables import WWI_TABLES


def bronze_counts() -> dict[str, int]:
    fs = pyarrow_s3()
    counts: dict[str, int] = {}
    for spec in WWI_TABLES:
        path = f"{settings.bronze_bucket}/wwi/{spec.resource_name}"
        counts[spec.resource_name] = ds.dataset(path, filesystem=fs, format="parquet").count_rows()
    return counts


def source_counts() -> dict[str, int]:
    engine = create_engine(settings.mssql_url)
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for spec in WWI_TABLES:
            n = conn.execute(
                text(f"SELECT COUNT(*) FROM [{spec.schema}].[{spec.table}]")
            ).scalar_one()
            counts[spec.resource_name] = int(n)
    engine.dispose()
    return counts


def _build_report(bronze: dict[str, int], source: dict[str, int] | None) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for spec in WWI_TABLES:
        name = spec.resource_name
        b = bronze.get(name, 0)
        if source is None:
            rows.append({"table": name, "bronze": b})
            continue
        s = source.get(name, 0)
        status = "OK" if s == b else ("APPEND" if b > s else "DIFF")
        rows.append({"table": name, "source": s, "bronze": b, "status": status})
    return {"bronze_bucket": settings.bronze_bucket, "tables": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Phase 1 Bronze row counts.")
    parser.add_argument(
        "--json", action="store_true", help="Emit structured JSON via the logger (for piping)."
    )
    args = parser.parse_args()
    if args.json:
        os.environ.setdefault("DE_LOG_FORMAT", "json")

    # Lazy import so the env var lands BEFORE the logger configures.
    from ..common.logging import get_logger

    log = get_logger(__name__)

    bronze = bronze_counts()
    source: dict[str, int] | None
    try:
        source = source_counts()
    except Exception as exc:  # noqa: BLE001 - source check is best-effort
        log.warning("source comparison skipped", extra={"reason": str(exc)})
        source = None

    report = _build_report(bronze, source)
    table_rows: list[dict[str, object]] = report["tables"]  # type: ignore[assignment]

    if args.json:
        log.info("verify report", extra=report)
        return

    # Pretty (human) output: tables stay aligned, but each line still goes through the logger.
    log.info("Bronze rows (Parquet on SeaweedFS):")
    for row in table_rows:
        log.info(f"  {row['table']:<22} {row['bronze']:>10,}")
    if source is not None:
        log.info("Source vs Bronze:")
        log.info(f"  {'table':<22} {'source':>10} {'bronze':>10}  {'status':>6}")
        for row in table_rows:
            line = (
                f"  {row['table']:<22} "
                f"{row['source']:>10,} {row['bronze']:>10,}  {row['status']:>6}"
            )
            log.info(line)


if __name__ == "__main__":
    main()
