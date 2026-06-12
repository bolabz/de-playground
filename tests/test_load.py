"""Pure-function tests for the producer side of the ES boundary (WS5).

Covers `to_actions` (row → ES bulk action), which became typed in WS4 6a: every row is
validated against FactSalesDoc before being yielded as `{_index, _id, _source}`.
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from de_playground.contracts import INDEX_FACT_SALES
from de_playground.load.to_elasticsearch import to_actions


def _row(order_line_id: int = 1, order_date: object = "2013-01-02") -> dict:
    return {
        "order_line_id": order_line_id,
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
        "order_date": order_date,
        "order_year": 2013,
        "order_month": 1,
    }


def test_to_actions_preserves_row_count():
    rows = [_row(i) for i in range(1, 11)]
    actions = list(to_actions(rows))
    assert len(actions) == 10


def test_to_actions_uses_shared_index_constant():
    [action] = list(to_actions([_row()]))
    assert action["_index"] == INDEX_FACT_SALES


def test_to_actions_keys_id_to_order_line_id():
    [action] = list(to_actions([_row(order_line_id=99)]))
    assert action["_id"] == 99


def test_to_actions_serializes_date_to_iso_string():
    """ES expects ISO; Pydantic's model_dump(mode='json') handles it."""
    [action] = list(to_actions([_row(order_date=date(2013, 1, 2))]))
    assert action["_source"]["order_date"] == "2013-01-02"


def test_to_actions_rejects_extra_field():
    """Producer guard — FactSalesDoc has extra='forbid', so bad shapes fail loud."""
    bad = _row() | {"unexpected": "boom"}
    with pytest.raises(ValueError, match="unexpected"):
        list(to_actions([bad]))


@given(ids=st.lists(st.integers(min_value=1, max_value=1_000_000), min_size=1, max_size=20))
def test_to_actions_id_is_always_set_and_unique_when_input_is(ids):
    actions = list(to_actions([_row(order_line_id=i) for i in ids]))
    assert [a["_id"] for a in actions] == ids
