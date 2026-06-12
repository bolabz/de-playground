"""CDC Bronze -> Silver: collapse the change feed into current state (deletes applied).

Reads the append-only change feed at bronze/wwi_cdc/<table> and, per primary key, keeps the
LATEST change by (change_lsn, change_seqval). If that latest change is a delete, the key is
dropped — which is exactly what the watermark-based Silver could never do.

Writes to silver/wwi_cdc/<table> (a separate prefix from the watermark Silver) so you can A/B
the two: delete a row in SQL Server, re-run extract-cdc + silver-cdc, and watch it disappear
here while it persists in silver/wwi/.

Operation codes: 1=delete, 2=insert, 3=update(before), 4=update(after). Ordering by
(lsn, seqval) descending makes the after-image (4) win over the before-image (3) for updates.
"""

from __future__ import annotations

from pyspark.errors import AnalysisException
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from de_playground.common.lake import ensure_bucket, s3a
from de_playground.common.logging import get_logger
from de_playground.config import settings
from de_playground.transform.silver import SILVER_TABLES, SilverSpec

log = get_logger(__name__)

_CHANGE_COLS = ["change_lsn", "change_seqval", "change_operation"]
_DELETE = 1


def collapse_changes(df: DataFrame, primary_key: str) -> DataFrame:
    """Latest change per key with deletes removed; change_* metadata dropped."""
    w = Window.partitionBy(primary_key).orderBy(
        F.col("change_lsn").desc(), F.col("change_seqval").desc()
    )
    latest = df.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    current = latest.filter(F.col("change_operation") != _DELETE)
    drop = [c for c in (*_CHANGE_COLS, "_dlt_id", "_dlt_load_id") if c in current.columns]
    return current.drop(*drop)


def build_silver_cdc(spark: SparkSession, specs: list[SilverSpec] = SILVER_TABLES) -> None:
    ensure_bucket(settings.silver_bucket)
    for spec in specs:
        src = s3a(settings.bronze_bucket, "wwi_cdc", spec.table)
        dst = s3a(settings.silver_bucket, "wwi_cdc", spec.table)
        try:
            feed = spark.read.parquet(src)
        except AnalysisException as err:
            # CDC only writes a Bronze folder for tables that had changes; a missing path
            # just means no changes captured for this table yet.
            if "PATH_NOT_FOUND" in str(err) or "Path does not exist" in str(err):
                log.info(
                    "silver-cdc skipped — no CDC changes captured yet",
                    extra={"table": spec.table},
                )
                continue
            raise
        out = collapse_changes(feed, spec.primary_key)
        out.write.format("delta").mode("overwrite").save(dst)
        log.info(
            "silver-cdc table written",
            extra={"table": spec.table, "rows": out.count(), "destination": dst},
        )
