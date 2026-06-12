"""Typed contracts at the producer ↔ serving boundary (WS4).

The Gold→Elasticsearch document is the canonical cross-plane contract. Both the producer
(`load.to_elasticsearch.to_actions`) and the serving plane (`api.main`) import these
Pydantic models — so the index name and document shape live ONCE (kills Finding 9 from
the hardening plan, which surfaced two independent declarations of the same
`"fact_sales"` string and document field set).

`de_playground.contracts` is the only module of de_playground that api/ depends on; the
serving-plane isolation is machine-enforced by `import-linter` (api may import contracts
and nothing else from de_playground — see pyproject.toml `[tool.importlinter]`).
"""

from __future__ import annotations

from datetime import date
from typing import get_type_hints

from pydantic import BaseModel, ConfigDict

# The Elasticsearch index that the producer writes to and the API reads from. Single
# source of truth — neither side should redeclare this string.
INDEX_FACT_SALES = "fact_sales"


class FactSalesDoc(BaseModel):
    """One row of gold/wwi/fact_sales = one document in the Elasticsearch index.

    Field names use snake_case (dlt-normalized — see CONTRIBUTING.md "Column-name
    contract"). Types feed `es_mapping()` below, so the ES mapping isn't a second
    hand-maintained declaration. `order_date` is a real `date` here and an ISO string on
    the wire — Pydantic's `model_dump(mode="json")` handles the conversion.

    Every WWI line carries `picked_quantity` (sourced from `Sales.OrderLines`), so
    there's no optional default here — a missing field flags upstream drift and fails
    loud at index time, by design.
    """

    model_config = ConfigDict(extra="forbid")

    order_line_id: int
    order_id: int
    customer_id: int
    salesperson_person_id: int
    stock_item_id: int
    description: str
    quantity: int
    picked_quantity: int
    unit_price: float
    tax_rate: float
    extended_price: float
    tax_amount: float
    line_total: float
    order_date: date
    order_year: int
    order_month: int


class SalesSearchResult(BaseModel):
    """Wrapper for /sales/search responses."""

    model_config = ConfigDict(extra="forbid")

    total: int
    results: list[FactSalesDoc]


# Per-field Elasticsearch type overrides for fields where the default Python-type
# mapping doesn't capture intent — `description` needs full-text search + a keyword
# subfield for exact-match aggregations, which is more than a plain `text` mapping.
_ES_FIELD_OVERRIDES: dict[str, dict[str, object]] = {
    "description": {
        "type": "text",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
    },
}

# Default Python-type → Elasticsearch-type mapping. Extend if a new annotation appears
# on FactSalesDoc — the codegen raises TypeError if a field's annotation isn't covered
# here or in `_ES_FIELD_OVERRIDES`, so drift can't slip in silently.
_PY_TO_ES: dict[type, dict[str, str]] = {
    int: {"type": "integer"},
    float: {"type": "double"},
    str: {"type": "keyword"},  # plain str gets keyword; text-search fields override
    date: {"type": "date"},
}


def es_mapping(model: type[BaseModel] = FactSalesDoc) -> dict[str, dict[str, object]]:
    """Derive an Elasticsearch property mapping from a Pydantic model's annotations.

    Eliminates the previous hand-maintained MAPPING dict in `load.to_elasticsearch` that
    duplicated FactSalesDoc's field set (residual Finding 9). Per-field overrides for
    fields whose Python type can't express the intended ES type (e.g. `description` =>
    text + keyword sub-field) live in `_ES_FIELD_OVERRIDES`.
    """
    hints = get_type_hints(model)
    properties: dict[str, dict[str, object]] = {}
    for field_name in model.model_fields:
        if field_name in _ES_FIELD_OVERRIDES:
            properties[field_name] = dict(_ES_FIELD_OVERRIDES[field_name])
            continue
        py_type = hints[field_name]
        if py_type not in _PY_TO_ES:
            raise TypeError(
                f"No ES mapping for field {field_name!r} of type {py_type!r}; "
                f"add an entry to _PY_TO_ES or _ES_FIELD_OVERRIDES."
            )
        properties[field_name] = dict(_PY_TO_ES[py_type])
    return properties


def build_query(
    q: str | None, customer_id: int | None, min_total: float | None
) -> dict[str, object]:
    """Pure Elasticsearch bool-query builder for /sales/search.

    Lives here (next to the models) rather than in api/main.py so both api and unit
    tests can import it without depending on FastAPI. Used by api/main.py's
    /sales/search route.
    """
    must: list[dict[str, object]] = []
    filt: list[dict[str, object]] = []
    if q:
        must.append({"multi_match": {"query": q, "fields": ["description"]}})
    if customer_id is not None:
        filt.append({"term": {"customer_id": customer_id}})
    if min_total is not None:
        filt.append({"range": {"line_total": {"gte": min_total}}})
    return {"bool": {"must": must or [{"match_all": {}}], "filter": filt}}
