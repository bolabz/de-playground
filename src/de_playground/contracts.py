"""Typed contracts at the producer ↔ serving boundary (WS4).

The Gold→Elasticsearch document is the canonical cross-plane contract. Both the producer
(`load.to_elasticsearch.to_actions`) and the serving plane (`api.main`) import these
Pydantic models — so the index name and document shape live ONCE (kills Finding 9 from the
hardening plan, which surfaced two independent declarations of the same `"fact_sales"`
string and document field set).

`de_playground.contracts` is the only module of de_playground that api/ depends on; the
serving-plane isolation the architecture asserts is about the *pipeline runtime*, not
shared schema. (If we ever grow a second consumer, this is the seam to split off.)
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# The Elasticsearch index that the producer writes to and the API reads from. Single
# source of truth — neither side should redeclare this string.
INDEX_FACT_SALES = "fact_sales"


class FactSalesDoc(BaseModel):
    """One row of gold/wwi/fact_sales = one document in the Elasticsearch index.

    Field names use snake_case (dlt-normalized — see CONTRIBUTING.md "Column-name
    contract"). Types match the explicit ES mapping in `load.to_elasticsearch.MAPPING`;
    keep the two in sync, or factor the mapping out of this module if drift becomes a
    risk. `order_date` is a real `date` here and an ISO string on the wire — the producer
    converts in `to_actions`.
    """

    model_config = ConfigDict(extra="forbid")

    order_line_id: int
    order_id: int
    customer_id: int
    salesperson_person_id: int
    stock_item_id: int
    description: str
    quantity: int
    picked_quantity: int = 0
    unit_price: float
    tax_rate: float
    extended_price: float
    tax_amount: float
    line_total: float
    order_date: date
    order_year: int
    order_month: int


class SalesSearchQuery(BaseModel):
    """The /sales/search filter combination (mirrors the FastAPI query parameters)."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = None
    customer_id: int | None = None
    min_total: float | None = None
    limit: int = Field(default=10, ge=1, le=100)


class SalesSearchResult(BaseModel):
    """Wrapper for /sales/search responses."""

    model_config = ConfigDict(extra="forbid")

    total: int
    results: list[FactSalesDoc]


def build_query(
    q: str | None, customer_id: int | None, min_total: float | None
) -> dict[str, object]:
    """Pure Elasticsearch bool-query builder for /sales/search.

    Lives here (next to the models) rather than in api/main.py so both api and unit tests
    can import it without depending on FastAPI. Used by api/main.py's /sales/search route.
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
