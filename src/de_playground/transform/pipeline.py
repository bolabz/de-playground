"""Phase 2 driver: Bronze -> Silver -> Gold (Delta on SeaweedFS), via local PySpark.

Run:  uv run python -m de_playground.transform              # both stages
      uv run python -m de_playground.transform silver       # just Silver
      uv run python -m de_playground.transform gold          # just Gold
(or `make transform` / `make silver` / `make gold`)
"""

from __future__ import annotations

import sys

from de_playground.common.spark import get_spark
from de_playground.transform.gold import build_gold
from de_playground.transform.silver import build_silver
from de_playground.transform.silver_cdc import build_silver_cdc

_STAGES = ("all", "silver", "gold", "silver-cdc")


def run(stage: str = "all") -> None:
    spark = get_spark(app_name=f"de-playground-transform-{stage}")
    try:
        if stage in ("all", "silver"):
            build_silver(spark)
        if stage in ("all", "gold"):
            build_gold(spark)
        if stage == "silver-cdc":  # CDC path is opt-in, not part of `all`
            build_silver_cdc(spark)
    finally:
        spark.stop()


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage not in _STAGES:
        raise SystemExit(f"unknown stage {stage!r}; use one of: {', '.join(_STAGES)}")
    run(stage)


if __name__ == "__main__":
    main()
