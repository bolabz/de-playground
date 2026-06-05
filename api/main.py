"""FastAPI serving plane — reads the derived Elasticsearch index, never the lake/OLTP.

The whole point of the serving plane: it answers HTTP requests fast because it hits a
read-optimized store (Elasticsearch's inverted index), isolated from the batch pipeline.

Endpoints:
  GET /health                 — liveness + ES connectivity
  GET /sales/search           — full-text on description + optional filters
  GET /sales/{order_line_id}  — fetch one document by id

Run locally (outside Docker):  ES_URL=http://localhost:9200 uvicorn main:app --reload
In the stack it runs from api/Dockerfile with ES_URL=http://elasticsearch:9200.
"""

from __future__ import annotations

import os

from elasticsearch import Elasticsearch, NotFoundError
from fastapi import FastAPI, HTTPException, Query

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
INDEX = "fact_sales"

app = FastAPI(title="de-playground sales API", version="0.1.0")
es = Elasticsearch(ES_URL)  # constructing the client doesn't connect


def build_query(q: str | None, customer_id: int | None, min_total: float | None) -> dict:
    """Pure query builder (unit-testable without a live ES)."""
    must: list[dict] = []
    filt: list[dict] = []
    if q:
        must.append({"multi_match": {"query": q, "fields": ["description"]}})
    if customer_id is not None:
        filt.append({"term": {"customer_id": customer_id}})
    if min_total is not None:
        filt.append({"range": {"line_total": {"gte": min_total}}})
    return {"bool": {"must": must or [{"match_all": {}}], "filter": filt}}


@app.get("/health")
def health() -> dict:
    try:
        return {"ok": True, "elasticsearch": es.ping(), "es_url": ES_URL}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "es_url": ES_URL}


@app.get("/sales/search")
def search(
    q: str | None = Query(None, description="full-text over the line description"),
    customer_id: int | None = None,
    min_total: float | None = Query(None, description="line_total >= this"),
    limit: int = Query(10, ge=1, le=100),
) -> dict:
    resp = es.search(index=INDEX, query=build_query(q, customer_id, min_total), size=limit)
    hits = resp["hits"]
    return {
        "total": hits["total"]["value"],
        "results": [h["_source"] for h in hits["hits"]],
    }


@app.get("/sales/{order_line_id}")
def get_one(order_line_id: int) -> dict:
    try:
        doc = es.get(index=INDEX, id=order_line_id)
    except NotFoundError as err:
        raise HTTPException(
            status_code=404, detail=f"order_line_id {order_line_id} not found"
        ) from err
    return doc["_source"]
