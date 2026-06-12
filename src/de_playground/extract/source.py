"""Build dlt resources that read WWI tables incrementally.

Each resource:
  * reads one table via SQLAlchemy,
  * tracks a high-watermark on the cursor column (dlt persists the max value as state),
  * appends to Bronze (raw landing — dedup/cleaning happens later in Silver),
  * declares a primary key so dlt can deduplicate rows sitting exactly on the watermark
    boundary across runs (the thing that makes re-runs idempotent).
"""

from __future__ import annotations

from collections.abc import Sequence

import dlt
from dlt.extract.resource import DltResource
from dlt.sources.sql_database import sql_table

from de_playground.extract.tables import WWI_TABLES, TableSpec


def _resource(spec: TableSpec, credentials: str) -> DltResource:
    return sql_table(
        credentials=credentials,
        schema=spec.schema,
        table=spec.table,
        incremental=dlt.sources.incremental(spec.cursor),
        primary_key=spec.primary_key,
        write_disposition="append",
        backend="sqlalchemy",  # most type-compatible across SQL Server types
    ).with_name(spec.resource_name)


def wwi_resources(credentials: str, specs: Sequence[TableSpec] = WWI_TABLES) -> list[DltResource]:
    """One DltResource per table, ready to hand to pipeline.run()."""
    return [_resource(s, credentials) for s in specs]
