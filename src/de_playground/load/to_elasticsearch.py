"""Phase 3: bulk-index gold/wwi/fact_sales into Elasticsearch (the derived serving store).

Run:  uv run python -m de_playground.load.to_elasticsearch   (or `make index`)

Reads Gold via delta-rs (no Spark), (re)creates the `fact_sales` index with an explicit
mapping, and bulk-loads documents keyed by order_line_id. Elasticsearch is DERIVED — it's
rebuilt from Gold, never the source of truth — so a full recreate each run is the simplest
idempotent strategy (re-running yields the same index).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from deltalake import DeltaTable
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from de_playground.common.lake import delta_storage_options
from de_playground.common.logging import get_logger, set_correlation_id
from de_playground.common.retry import retry_until
from de_playground.config import settings

log = get_logger(__name__)

INDEX = "fact_sales"

# Explicit mapping: description is full-text (with a keyword subfield for exact match/aggs);
# ids/measures typed so range + term queries and Kibana aggregations behave.
MAPPING: dict[str, dict] = {
    "order_line_id": {"type": "integer"},
    "order_id": {"type": "integer"},
    "customer_id": {"type": "integer"},
    "salesperson_person_id": {"type": "integer"},
    "stock_item_id": {"type": "integer"},
    "description": {
        "type": "text",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
    },
    "quantity": {"type": "integer"},
    "picked_quantity": {"type": "integer"},
    "unit_price": {"type": "double"},
    "tax_rate": {"type": "double"},
    "extended_price": {"type": "double"},
    "tax_amount": {"type": "double"},
    "line_total": {"type": "double"},
    "order_date": {"type": "date"},
    "order_year": {"type": "integer"},
    "order_month": {"type": "integer"},
}


def wait_for_es(es: Elasticsearch) -> None:
    """Elasticsearch needs ~30s to accept requests after its container starts."""
    retry_until(es.ping, predicate=bool)


def read_fact_sales() -> list[dict]:
    dt = DeltaTable(
        f"s3://{settings.gold_bucket}/wwi/fact_sales",
        storage_options=delta_storage_options(),
    )
    return dt.to_pyarrow_table().to_pylist()


def to_actions(rows: list[dict]) -> Iterator[dict]:
    for row in rows:
        source = dict(row)
        order_date = source.get("order_date")
        if isinstance(order_date, date):
            source["order_date"] = order_date.isoformat()  # ES wants an ISO string
        yield {"_index": INDEX, "_id": source["order_line_id"], "_source": source}


def run() -> None:
    set_correlation_id()
    es = Elasticsearch(settings.es_url)
    wait_for_es(es)

    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
    es.indices.create(index=INDEX, mappings={"properties": MAPPING})

    rows = read_fact_sales()
    indexed, errors = bulk(es, to_actions(rows))
    es.indices.refresh(index=INDEX)
    total = es.count(index=INDEX)["count"]
    n_errors = len(errors) if isinstance(errors, list) else int(errors)
    log.info(
        "indexed docs",
        extra={"index": INDEX, "indexed": indexed, "errors": n_errors, "total": total},
    )


if __name__ == "__main__":
    run()
