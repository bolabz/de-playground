"""Phase 3: bulk-index gold/wwi/fact_sales into Elasticsearch (the derived serving store).

Run:  uv run python -m de_playground.load.to_elasticsearch   (or `make index`)

Reads Gold via delta-rs (no Spark), (re)creates the `fact_sales` index with an explicit
mapping, and bulk-loads documents keyed by order_line_id. Elasticsearch is DERIVED — it's
rebuilt from Gold, never the source of truth — so a full recreate each run is the simplest
idempotent strategy (re-running yields the same index).
"""

from __future__ import annotations

from collections.abc import Iterator

from deltalake import DeltaTable
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from de_playground.common.lake import delta_storage_options
from de_playground.common.logging import get_logger, set_correlation_id
from de_playground.common.retry import retry_until
from de_playground.config import settings
from de_playground.contracts import INDEX_FACT_SALES, FactSalesDoc, es_mapping

log = get_logger(__name__)

INDEX = INDEX_FACT_SALES  # backward-compat alias; new code uses INDEX_FACT_SALES directly

# WS4 6a post-mortem: was a 16-entry hand-maintained dict that duplicated FactSalesDoc's
# field set (residual Finding 9 — every new Pydantic field had to be added in two places
# or risk drift). Now derived once from the Pydantic model via `es_mapping()`; the
# codegen raises TypeError if a future FactSalesDoc field has no Python→ES type
# mapping, so drift can't slip in silently.
MAPPING: dict[str, dict[str, object]] = es_mapping(FactSalesDoc)


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
    """Validate each Gold row against FactSalesDoc, then yield an ES bulk action.

    Pydantic enforces the producer contract — extra fields or missing fields fail loud at
    index time rather than landing as a half-broken document. `mode="json"` returns date
    as an ISO string (matching what ES expects), so we don't need the old isoformat dance.
    """
    for row in rows:
        doc = FactSalesDoc.model_validate(row)
        source = doc.model_dump(mode="json")
        yield {
            "_index": INDEX_FACT_SALES,
            "_id": doc.order_line_id,
            "_source": source,
        }


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
