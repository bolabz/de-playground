"""Cluster entry point for the Phase 2 transforms — run via spark-submit.

This is the file `spark-submit` executes on the driver. It imports the same build_silver /
build_gold logic used in local mode, but builds the SparkSession with get_cluster_spark()
(master = SPARK_MASTER_URL, jars baked into the image — no Ivy, no --packages).

The de_playground package reaches the driver/executors via `--py-files <wheel>` (see the
spark-submit service in docker-compose.yml). Note: these transforms are pure DataFrame ops,
so executors never actually import de_playground — the JVM runs the plan. --py-files is still
the right mechanism, and it's what you'd need the moment you add a Python UDF.
"""

from __future__ import annotations

import sys

from de_playground.common.spark import get_cluster_spark
from de_playground.transform.gold import build_gold
from de_playground.transform.silver import build_silver


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage not in ("all", "silver", "gold"):
        raise SystemExit(f"unknown stage {stage!r}; use: all | silver | gold")

    spark = get_cluster_spark(app_name=f"de-playground-cluster-{stage}")
    try:
        if stage in ("all", "silver"):
            build_silver(spark)
        if stage in ("all", "gold"):
            build_gold(spark)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
