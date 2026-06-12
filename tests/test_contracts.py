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
    SalesSearchResult,
    build_query,
    es_mapping,
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


# ---------------------------------------------------------------------------------------
# es_mapping — codegen ES mapping from FactSalesDoc annotations
# ---------------------------------------------------------------------------------------


def test_es_mapping_covers_every_pydantic_field():
    mapping = es_mapping(FactSalesDoc)
    assert set(mapping) == set(FactSalesDoc.model_fields)


def test_es_mapping_assigns_python_types_to_es_types():
    mapping = es_mapping(FactSalesDoc)
    assert mapping["order_line_id"]["type"] == "integer"  # int
    assert mapping["unit_price"]["type"] == "double"  # float
    assert mapping["order_date"]["type"] == "date"  # date


def test_es_mapping_overrides_description_to_text_keyword():
    """Description is a special case: full-text + an exact-match keyword subfield."""
    desc = es_mapping(FactSalesDoc)["description"]
    assert desc["type"] == "text"
    assert desc["fields"]["keyword"]["type"] == "keyword"


def test_es_mapping_returns_fresh_dicts_per_call():
    """Caller mutation must not poison the override table or the default map."""
    m1 = es_mapping(FactSalesDoc)
    m1["order_line_id"]["type"] = "BOGUS"
    m2 = es_mapping(FactSalesDoc)
    assert m2["order_line_id"]["type"] == "integer"


def test_es_mapping_rejects_unmapped_python_types():
    """A future model with an unrecognised annotation should fail loud, not silently."""
    from pydantic import BaseModel as _BM
    from pydantic import ConfigDict as _CD

    class Bad(_BM):
        model_config = _CD(extra="forbid")
        weird: list[int]  # no entry in _PY_TO_ES

    with pytest.raises(TypeError, match="No ES mapping"):
        es_mapping(Bad)
