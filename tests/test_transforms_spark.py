"""Spark-backed transform tests (WS5).

All tests in this module require a JVM + PySpark; opt-in via the `pyspark` marker — default
CI stays Java-free, the opt-in CI job runs `pytest -m pyspark` with JDK 17 installed.
The `spark` fixture lives in tests/conftest.py.

Coverage scope (from PYTHON_HARDENING_PLAN.md WS5 step 3):
  - silver_cdc.collapse_changes — synthetic change feed → expected current state.
  - (gold.build_fact_sales, gold.build_fact_invoices, silver.conform — to add).
"""

from __future__ import annotations

import pytest

# Skip the whole module at collection time when pyspark isn't installed (default `dev`-only
# sync). Otherwise the top-level `from de_playground.transform...` would explode before
# pytest gets a chance to consult the `pyspark` marker.
pytest.importorskip("pyspark")

from de_playground.transform.silver_cdc import collapse_changes  # noqa: E402

pytestmark = pytest.mark.pyspark


def test_collapse_changes_picks_latest_per_key(spark):
    """Two updates for the same key — the higher (lsn, seqval) wins."""
    rows = [
        # (pk, change_lsn, change_seqval, change_operation, value)
        (1, "0000000000000000A001", "00000000000000000001", 4, "v_old"),
        (1, "0000000000000000A002", "00000000000000000001", 4, "v_new"),
    ]
    df = spark.createDataFrame(
        rows, ["order_id", "change_lsn", "change_seqval", "change_operation", "value"]
    )
    [out] = collapse_changes(df, primary_key="order_id").collect()
    assert out["order_id"] == 1
    assert out["value"] == "v_new"


def test_collapse_changes_drops_keys_whose_latest_op_is_delete(spark):
    """Insert then delete — the row should disappear from the output."""
    rows = [
        (1, "0000000000000000A001", "00000000000000000001", 2, "ins"),  # insert
        (1, "0000000000000000A002", "00000000000000000001", 1, "del"),  # delete
        (2, "0000000000000000A003", "00000000000000000001", 2, "ins_kept"),
    ]
    df = spark.createDataFrame(
        rows, ["order_id", "change_lsn", "change_seqval", "change_operation", "value"]
    )
    out = {r["order_id"]: r["value"] for r in collapse_changes(df, "order_id").collect()}
    assert out == {2: "ins_kept"}


def test_collapse_changes_strips_change_metadata_columns(spark):
    rows = [
        (1, "0000000000000000A001", "00000000000000000001", 2, "v"),
    ]
    df = spark.createDataFrame(
        rows, ["order_id", "change_lsn", "change_seqval", "change_operation", "value"]
    )
    result_cols = collapse_changes(df, "order_id").columns
    assert "change_lsn" not in result_cols
    assert "change_seqval" not in result_cols
    assert "change_operation" not in result_cols
    assert "order_id" in result_cols
    assert "value" in result_cols
