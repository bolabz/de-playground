"""Bronze -> Silver: clean and conform.

Bronze is raw and append-only, so a row that was updated at source lands multiple times.
Silver keeps exactly one row per primary key — the latest by `last_edited_when` (ties broken
by dlt load id, so it's deterministic) — and drops dlt's bookkeeping columns. Silver is
rebuilt in full from Bronze (overwrite), which makes reprocessing safe and repeatable.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from ..common.lake import ensure_bucket, s3a
from ..common.logging import get_logger
from ..config import settings

log = get_logger(__name__)

_DLT_COLS = ["_dlt_id", "_dlt_load_id"]


@dataclass(frozen=True)
class SilverSpec:
    table: str  # bronze + silver folder name, e.g. "sales_orders"
    primary_key: str  # snake_case PK (as dlt normalized it)
    cursor: str = "last_edited_when"


# Column names are dlt's snake_case normalization of the WWI originals (verified).
SILVER_TABLES: list[SilverSpec] = [
    SilverSpec("sales_orders", "order_id"),
    SilverSpec("sales_orderlines", "order_line_id"),
    SilverSpec("sales_invoices", "invoice_id"),
    SilverSpec("sales_invoicelines", "invoice_line_id"),
]


def dedupe_latest(df: DataFrame, primary_key: str, cursor: str) -> DataFrame:
    """Keep one row per primary_key: the newest by cursor (then by dlt load id)."""
    order_by = [F.col(cursor).desc()]
    if "_dlt_load_id" in df.columns:
        order_by.append(F.col("_dlt_load_id").desc())
    w = Window.partitionBy(primary_key).orderBy(*order_by)
    return df.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")


def drop_dlt_columns(df: DataFrame) -> DataFrame:
    return df.drop(*[c for c in _DLT_COLS if c in df.columns])


def conform(df: DataFrame, primary_key: str, cursor: str) -> DataFrame:
    """The pure transform: dedupe to latest, then drop dlt metadata. Unit-testable."""
    return drop_dlt_columns(dedupe_latest(df, primary_key, cursor))


def build_silver(spark: SparkSession) -> None:
    ensure_bucket(settings.silver_bucket)
    for spec in SILVER_TABLES:
        src = s3a(settings.bronze_bucket, "wwi", spec.table)
        dst = s3a(settings.silver_bucket, "wwi", spec.table)
        raw = spark.read.parquet(src)
        out = conform(raw, spec.primary_key, spec.cursor)
        out.write.format("delta").mode("overwrite").save(dst)
        log.info(
            "silver table written",
            extra={"table": spec.table, "rows": out.count(), "destination": dst},
        )
