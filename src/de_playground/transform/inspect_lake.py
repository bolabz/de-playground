"""Inspect any medallion layer — row counts, schema, partitions, sample rows.

Run:  uv run python -m de_playground.transform.inspect_lake <bronze|silver|gold>
      (or `make inspect LAYER=silver`)
      Add `--json` to emit a structured JSON report instead of the pretty table.

Bronze is Parquet (read via pyarrow); Silver/Gold are Delta (read via delta-rs). Neither
path needs Spark/JVM — handy for a quick look without spinning anything up.
"""

from __future__ import annotations

import argparse
import os

import pyarrow.dataset as pads
from deltalake import DeltaTable

from de_playground.common.lake import delta_storage_options, pyarrow_s3
from de_playground.config import settings

# layer -> (format, settings bucket attr, tables)
_LAYERS: dict[str, tuple[str, str, list[str]]] = {
    "bronze": (
        "parquet",
        "bronze_bucket",
        ["sales_orders", "sales_orderlines", "sales_invoices", "sales_invoicelines"],
    ),
    "silver": (
        "delta",
        "silver_bucket",
        ["sales_orders", "sales_orderlines", "sales_invoices", "sales_invoicelines"],
    ),
    "gold": (
        "delta",
        "gold_bucket",
        ["fact_sales", "agg_sales_daily", "fact_invoices", "agg_billed_daily"],
    ),
}


def _sample_rows(table, max_cols: int = 6, n: int = 3) -> list[dict]:
    cols = table.column_names[:max_cols]
    return table.select(cols).slice(0, n).to_pylist()


def _inspect_parquet(bucket: str, name: str) -> dict[str, object]:
    ds = pads.dataset(f"{bucket}/wwi/{name}", filesystem=pyarrow_s3(), format="parquet")
    return {
        "table": name,
        "rows": ds.count_rows(),
        "cols": len(ds.schema.names),
        "samples": _sample_rows(ds.head(3)),
    }


def _inspect_delta(bucket: str, name: str) -> dict[str, object]:
    dt = DeltaTable(f"s3://{bucket}/wwi/{name}", storage_options=delta_storage_options())
    ds = dt.to_pyarrow_dataset()
    return {
        "table": name,
        "rows": ds.count_rows(),
        "cols": len(ds.schema.names),
        "version": dt.version(),
        "partition_columns": dt.metadata().partition_columns,
        "samples": _sample_rows(ds.head(3)),
    }


def collect(layer: str) -> dict[str, object]:
    fmt, bucket_attr, tables = _LAYERS[layer]
    bucket = getattr(settings, bucket_attr)
    results = [
        _inspect_parquet(bucket, name) if fmt == "parquet" else _inspect_delta(bucket, name)
        for name in tables
    ]
    return {"layer": layer, "format": fmt, "bucket": bucket, "tables": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a medallion layer.")
    parser.add_argument("layer", nargs="?", default="gold", choices=list(_LAYERS))
    parser.add_argument(
        "--json", action="store_true", help="Emit structured JSON via the logger (for piping)."
    )
    args = parser.parse_args()
    if args.json:
        os.environ.setdefault("DE_LOG_FORMAT", "json")

    from de_playground.common.logging import (
        get_logger,  # lazy: respect DE_LOG_FORMAT set just above
    )

    log = get_logger(__name__)

    report = collect(args.layer)
    entries: list[dict[str, object]] = report["tables"]  # type: ignore[assignment]

    if args.json:
        log.info("inspect report", extra=report)
        return

    log.info(f"== {report['layer']} ({report['format']}) @ s3://{report['bucket']}/wwi ==")
    for entry in entries:
        parts = entry.get("partition_columns")
        version = entry.get("version")
        suffix = ""
        if version is not None:
            suffix = f", v{version}"
            if parts:
                suffix += f", partitioned by {parts}"
        log.info(f"  {entry['table']}: {entry['rows']:,} rows, {entry['cols']} cols{suffix}")
        samples: list[dict[str, object]] = entry["samples"]  # type: ignore[assignment]
        for row in samples:
            log.info(f"    {row}")


if __name__ == "__main__":
    main()
    # delta-rs keeps non-daemon Rust threads alive after main() returns; without an explicit
    # exit, Python waits on them and a redirected `> file 2>&1` invocation never terminates.
    # Pipe-to-consumer invocations work because SIGPIPE kills the process — but the regression
    # oracle (`make baseline`/`make regression`) writes to a file, so it hits the hang.
    os._exit(0)
