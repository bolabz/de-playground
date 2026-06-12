"""Spark-backed transform tests (WS5).

All tests in this module require a JVM + PySpark; opt-in via the `pyspark` marker — default
CI stays Java-free, the opt-in CI job runs `pytest -m pyspark` with JDK 17 installed.
The `spark` fixture lives in tests/conftest.py.

Coverage scope (from PYTHON_HARDENING_PLAN.md WS5 step 3):
  - silver_cdc.collapse_changes — synthetic change feed → expected current state.
  - silver.conform — dedupe-to-latest + drop dlt bookkeeping.
  - gold.build_fact_sales — orders ⋈ lines + derived revenue measures.
  - gold.build_fact_invoices — invoices ⋈ invoice_lines + line_profit + measures.
"""

from __future__ import annotations

from datetime import date

import pytest

# Skip the whole module at collection time when pyspark isn't installed (default `dev`-only
# sync). Otherwise the top-level `from de_playground.transform...` would explode before
# pytest gets a chance to consult the `pyspark` marker.
pytest.importorskip("pyspark")

from de_playground.transform.gold import (  # noqa: E402
    build_fact_invoices,
    build_fact_sales,
)
from de_playground.transform.silver import conform  # noqa: E402
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


# ---------------------------------------------------------------------------------------
# silver.conform — dedupe-to-latest + drop dlt bookkeeping
# ---------------------------------------------------------------------------------------


def test_silver_conform_keeps_latest_by_cursor(spark):
    """Same PK, multiple cursor values — keep the row with the newest last_edited_when."""
    rows = [
        # (order_id, last_edited_when, _dlt_id, _dlt_load_id, value)
        (1, "2024-01-01 00:00:00", "a", "1", "stale"),
        (1, "2024-01-02 00:00:00", "b", "2", "fresh"),
        (2, "2024-01-01 00:00:00", "c", "1", "only"),
    ]
    df = spark.createDataFrame(
        rows, ["order_id", "last_edited_when", "_dlt_id", "_dlt_load_id", "value"]
    )
    out = {r["order_id"]: r["value"] for r in conform(df, "order_id", "last_edited_when").collect()}
    assert out == {1: "fresh", 2: "only"}


def test_silver_conform_drops_dlt_columns(spark):
    rows = [(1, "2024-01-01 00:00:00", "abc", "42", "v")]
    df = spark.createDataFrame(
        rows, ["order_id", "last_edited_when", "_dlt_id", "_dlt_load_id", "value"]
    )
    cols = conform(df, "order_id", "last_edited_when").columns
    assert "_dlt_id" not in cols
    assert "_dlt_load_id" not in cols
    assert "order_id" in cols
    assert "last_edited_when" in cols
    assert "value" in cols


def test_silver_conform_breaks_cursor_ties_by_dlt_load_id(spark):
    """When two rows have identical cursors, the higher _dlt_load_id wins (deterministic)."""
    rows = [
        (1, "2024-01-01 00:00:00", "a", "5", "loser"),
        (1, "2024-01-01 00:00:00", "b", "9", "winner"),
    ]
    df = spark.createDataFrame(
        rows, ["order_id", "last_edited_when", "_dlt_id", "_dlt_load_id", "value"]
    )
    [out] = conform(df, "order_id", "last_edited_when").collect()
    assert out["value"] == "winner"


# ---------------------------------------------------------------------------------------
# gold.build_fact_sales — orders ⋈ lines + derived measures + year/month
# ---------------------------------------------------------------------------------------


def _make_orders(spark):
    return spark.createDataFrame(
        [
            # (order_id, customer_id, salesperson_person_id, order_date)
            (1, 42, 7, date(2024, 3, 15)),
            (2, 43, 9, date(2024, 4, 1)),
            # order_id=99 has no matching lines — should fall out of the inner join.
            (99, 50, 1, date(2024, 5, 1)),
        ],
        ["order_id", "customer_id", "salesperson_person_id", "order_date"],
    )


def _make_lines(spark):
    return spark.createDataFrame(
        [
            # (order_line_id, order_id, stock_item_id, description, quantity, unit_price,
            #  tax_rate, picked_quantity)
            (10, 1, 100, "USB widget", 4, 25.0, 15.0, 4),
            (11, 1, 101, "SD card", 2, 50.0, 15.0, 2),
            (20, 2, 100, "USB widget", 1, 25.0, 10.0, 0),
            # line for order 999 — order missing, should fall out of the join too.
            (30, 999, 100, "orphan", 1, 1.0, 0.0, 0),
        ],
        [
            "order_line_id",
            "order_id",
            "stock_item_id",
            "description",
            "quantity",
            "unit_price",
            "tax_rate",
            "picked_quantity",
        ],
    )


def test_build_fact_sales_inner_join_drops_unmatched(spark):
    fact = build_fact_sales(_make_orders(spark), _make_lines(spark)).collect()
    assert len(fact) == 3  # 2 lines for order 1, 1 for order 2; orphan + order-99 dropped
    assert {row["order_line_id"] for row in fact} == {10, 11, 20}


def test_build_fact_sales_computes_revenue_measures(spark):
    fact = {
        r["order_line_id"]: r
        for r in build_fact_sales(_make_orders(spark), _make_lines(spark)).collect()
    }
    line_10 = fact[10]  # quantity=4, unit_price=25.0, tax_rate=15.0
    assert line_10["extended_price"] == 100.0  # 4 * 25
    assert line_10["tax_amount"] == 15.0  # 100 * 15 / 100
    assert line_10["line_total"] == 115.0  # 100 + 15
    assert line_10["order_year"] == 2024
    assert line_10["order_month"] == 3


def test_build_fact_sales_propagates_order_metadata(spark):
    fact = {
        r["order_line_id"]: r
        for r in build_fact_sales(_make_orders(spark), _make_lines(spark)).collect()
    }
    # Both lines on order 1 inherit the same customer/salesperson/date.
    assert fact[10]["customer_id"] == 42
    assert fact[11]["customer_id"] == 42
    assert fact[10]["salesperson_person_id"] == 7
    # Line 20 belongs to order 2.
    assert fact[20]["customer_id"] == 43
    assert fact[20]["order_year"] == 2024
    assert fact[20]["order_month"] == 4


# ---------------------------------------------------------------------------------------
# gold.build_fact_invoices — invoices ⋈ invoice_lines + line_profit
# ---------------------------------------------------------------------------------------


def _make_invoices(spark):
    return spark.createDataFrame(
        [
            # (invoice_id, customer_id, salesperson_person_id, invoice_date, is_credit_note)
            (1, 42, 7, date(2024, 6, 10), False),
            (2, 43, 9, date(2024, 7, 22), True),  # credit note
        ],
        [
            "invoice_id",
            "customer_id",
            "salesperson_person_id",
            "invoice_date",
            "is_credit_note",
        ],
    )


def _make_invoice_lines(spark):
    return spark.createDataFrame(
        [
            # (invoice_line_id, invoice_id, stock_item_id, description, quantity,
            #  unit_price, tax_rate, line_profit)
            (100, 1, 200, "USB", 5, 20.0, 15.0, 30.0),
            (101, 1, 201, "Cable", 2, 10.0, 10.0, 4.5),
            (200, 2, 200, "USB", -1, 20.0, 15.0, -6.0),  # credit-note line
        ],
        [
            "invoice_line_id",
            "invoice_id",
            "stock_item_id",
            "description",
            "quantity",
            "unit_price",
            "tax_rate",
            "line_profit",
        ],
    )


def test_build_fact_invoices_computes_revenue_and_carries_profit(spark):
    fact = {
        r["invoice_line_id"]: r
        for r in build_fact_invoices(_make_invoices(spark), _make_invoice_lines(spark)).collect()
    }
    line_100 = fact[100]  # qty=5, unit=20, tax=15
    assert line_100["extended_price"] == 100.0
    assert line_100["tax_amount"] == 15.0
    assert line_100["line_total"] == 115.0
    assert line_100["line_profit"] == 30.0
    assert line_100["invoice_year"] == 2024
    assert line_100["invoice_month"] == 6
    assert line_100["is_credit_note"] is False


def test_build_fact_invoices_preserves_credit_note_flag_and_negatives(spark):
    fact = {
        r["invoice_line_id"]: r
        for r in build_fact_invoices(_make_invoices(spark), _make_invoice_lines(spark)).collect()
    }
    credit = fact[200]
    assert credit["is_credit_note"] is True
    assert credit["extended_price"] == -20.0  # negative qty * positive price
    assert credit["line_profit"] == -6.0


def test_build_fact_invoices_inner_join_shape(spark):
    """Same join semantics as fact_sales — orphan lines on either side fall out."""
    invoices = _make_invoices(spark)
    invoice_lines = _make_invoice_lines(spark).union(
        spark.createDataFrame(
            [(999, 99, 0, "orphan", 0, 0.0, 0.0, 0.0)],
            [
                "invoice_line_id",
                "invoice_id",
                "stock_item_id",
                "description",
                "quantity",
                "unit_price",
                "tax_rate",
                "line_profit",
            ],
        )
    )
    fact = build_fact_invoices(invoices, invoice_lines).collect()
    assert 999 not in {r["invoice_line_id"] for r in fact}
    assert len(fact) == 3  # 2 lines on inv 1 + 1 on inv 2
