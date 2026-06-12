"""DB-free unit tests for the typed cross-plane contracts (WS5).

Covers `build_query` (the ES bool-query builder) and the Pydantic models. These are pure
functions; no Spark, no live ES, no docker required — CI-friendly.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from de_playground.contracts import (
    INDEX_FACT_SALES,
    FactSalesDoc,
    SalesSearchQuery,
    SalesSearchResult,
    build_query,
)

# ---------------------------------------------------------------------------------------
# build_query — every filter combination + hypothesis property
# ---------------------------------------------------------------------------------------


def test_build_query_index_constant_unchanged():
    assert INDEX_FACT_SALES == "fact_sales"


@pytest.mark.parametrize(
    ("q", "customer_id", "min_total", "expected_must", "expected_filt_count"),
    [
        (None, None, None, "match_all", 0),
        ("USB", None, None, "multi_match", 0),
        (None, 1, None, "match_all", 1),
        (None, None, 100.0, "match_all", 1),
        ("USB", 1, None, "multi_match", 1),
        ("USB", None, 100.0, "multi_match", 1),
        (None, 1, 100.0, "match_all", 2),
        ("USB", 1, 100.0, "multi_match", 2),
    ],
)
def test_build_query_filter_matrix(q, customer_id, min_total, expected_must, expected_filt_count):
    bool_q = build_query(q, customer_id, min_total)["bool"]
    assert expected_must in next(iter(bool_q["must"][0]))
    assert len(bool_q["filter"]) == expected_filt_count


@given(
    q=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    customer_id=st.one_of(st.none(), st.integers(min_value=1, max_value=10_000)),
    min_total=st.one_of(st.none(), st.floats(min_value=0, max_value=10_000, allow_nan=False)),
)
def test_build_query_always_structurally_valid(q, customer_id, min_total):
    """Property: for any filter combination, output is a valid ES bool query."""
    result = build_query(q, customer_id, min_total)
    bool_q = result["bool"]
    # `must` is never empty (match_all when no text query)
    assert isinstance(bool_q["must"], list)
    assert len(bool_q["must"]) >= 1
    # `filter` count == number of non-None filter args
    expected_filter_count = sum(1 for v in (customer_id, min_total) if v is not None)
    assert len(bool_q["filter"]) == expected_filter_count


# ---------------------------------------------------------------------------------------
# FactSalesDoc / SalesSearchResult — extra="forbid" + type coercion
# ---------------------------------------------------------------------------------------


def _sample_row() -> dict:
    return {
        "order_line_id": 1,
        "order_id": 100,
        "customer_id": 7,
        "salesperson_person_id": 2,
        "stock_item_id": 67,
        "description": "USB rocket launcher",
        "quantity": 10,
        "picked_quantity": 10,
        "unit_price": 25.0,
        "tax_rate": 15.0,
        "extended_price": 250.0,
        "tax_amount": 37.5,
        "line_total": 287.5,
        "order_date": "2013-01-02",
        "order_year": 2013,
        "order_month": 1,
    }


def test_fact_sales_doc_accepts_valid_row():
    doc = FactSalesDoc.model_validate(_sample_row())
    assert doc.order_line_id == 1
    assert doc.description == "USB rocket launcher"


def test_fact_sales_doc_rejects_extra_field():
    bad = _sample_row() | {"unexpected_field": "boom"}
    with pytest.raises(ValueError, match="unexpected_field"):
        FactSalesDoc.model_validate(bad)


def test_sales_search_result_round_trips():
    result = SalesSearchResult(total=1, results=[FactSalesDoc.model_validate(_sample_row())])
    dumped = result.model_dump(mode="json")
    assert dumped["total"] == 1
    assert dumped["results"][0]["order_date"] == "2013-01-02"  # ISO string on the wire


def test_sales_search_query_defaults():
    q = SalesSearchQuery()
    assert q.limit == 10
    assert q.q is None
    assert q.customer_id is None


@pytest.mark.parametrize("bad_limit", [0, 101, -1])
def test_sales_search_query_limit_bounds(bad_limit):
    with pytest.raises(ValueError, match=r"(greater_than_equal|less_than_equal)"):
        SalesSearchQuery(limit=bad_limit)
