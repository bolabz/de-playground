"""FastAPI serving plane — reads the derived Elasticsearch index, never the lake/OLTP.

The whole point of the serving plane: it answers HTTP requests fast because it hits a
read-optimized store (Elasticsearch's inverted index), isolated from the batch pipeline.

Endpoints:
  GET /health                 — liveness + ES connectivity
  GET /sales/search           — full-text on description + optional filters
  GET /sales/{order_line_id}  — fetch one document by id

Cross-plane contract: FactSalesDoc, SalesSearchResult, INDEX_FACT_SALES, and the
`build_query` helper all come from `de_playground.contracts` — the same Pydantic models
the producer (load.to_elasticsearch) uses to validate Gold rows on the way IN to
Elasticsearch (WS4). import-linter's `api may only import de_playground.contracts`
contract is what keeps that the *only* cross-plane import.

Run locally (outside Docker):  ES_URL=http://localhost:9200 uvicorn main:app --reload
In the stack it runs from api/Dockerfile with ES_URL=http://elasticsearch:9200.
"""

from __future__ import annotations

import os

from elasticsearch import ApiError as ESApiError
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch import TransportError as ESTransportError
from fastapi import FastAPI, HTTPException, Query

from de_playground.contracts import (
    INDEX_FACT_SALES,
    FactSalesDoc,
    SalesSearchResult,
    build_query,
)

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")

app = FastAPI(title="de-playground sales API", version="0.1.0")
es = Elasticsearch(ES_URL)  # constructing the client doesn't connect


@app.get("/health")
def health() -> dict:
    """Liveness + ES connectivity. Falls back to a typed-error response if the ES
    transport layer fails (e.g. connection refused during cold start) — only the
    elasticsearch client's own exceptions are caught, not a blanket Exception."""
    try:
        return {"ok": True, "elasticsearch": es.ping(), "es_url": ES_URL}
    except (ESTransportError, ESApiError, OSError) as exc:
        return {"ok": False, "error": str(exc), "es_url": ES_URL}


@app.get("/sales/search", response_model=SalesSearchResult)
def search(
    q: str | None = Query(None, description="full-text over the line description"),
    customer_id: int | None = None,
    min_total: float | None = Query(None, description="line_total >= this"),
    limit: int = Query(10, ge=1, le=100),
) -> SalesSearchResult:
    resp = es.search(
        index=INDEX_FACT_SALES, query=build_query(q, customer_id, min_total), size=limit
    )
    hits = resp["hits"]
    return SalesSearchResult(
        total=hits["total"]["value"],
        results=[FactSalesDoc.model_validate(h["_source"]) for h in hits["hits"]],
    )


@app.get("/sales/{order_line_id}", response_model=FactSalesDoc)
def get_one(order_line_id: int) -> FactSalesDoc:
    try:
        doc = es.get(index=INDEX_FACT_SALES, id=str(order_line_id))
    except NotFoundError as err:
        raise HTTPException(
            status_code=404, detail=f"order_line_id {order_line_id} not found"
        ) from err
    return FactSalesDoc.model_validate(doc["_source"])
