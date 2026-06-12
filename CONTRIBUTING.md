# Contributing

This is a personal proof-of-concept data-engineering pipeline, built to be a long-term
reference and to mirror an Azure stack with free/OSS tooling. The bar: a teammate (or
future-you) should be able to read it, run it solo, and extend it without spelunking.

See `README.md` for how to run everything and `docs/ARCHITECTURE.md` for the design. Future
work is tracked in `docs/BACKLOG.md`; **when something fails, go to `docs/TROUBLESHOOTING.md`
first** — that's the canonical symptom→cause→fix runbook (env races, JDK / Apple-Silicon /
compose-path / readiness gotchas all live there). Monitoring is in `docs/OBSERVABILITY.md`.
CI (ruff + mypy + pytest) runs on every PR; install the matching pre-commit hooks with
`uv run pre-commit install`.

## Setup recap

Prereqs (macOS / Apple Silicon): Docker Desktop, [uv](https://docs.astral.sh/uv/), JDK 17
(`brew install openjdk@17` — Spark 3.5 supports Java 8/11/17 only), and the Microsoft ODBC
Driver 18 (`brew install msodbcsql18`). **Use a Python 3.11 venv** (`uv venv --python 3.11`);
PySpark 3.5 is only tested through ~3.11/3.12.

```sh
uv venv --python 3.11 && make sync-all      # all extras at once (avoids extra-churn; see below)
cp .env.example .env                         # local-only placeholders; .env is gitignored
```

## Conventions

- **Formatting/linting:** `ruff` (line length 100; expanded `select` with TID/RUF/SIM/PTH/
  PT/LOG/G/RET/C4/S) + `mypy --strict` (scoped overrides for Spark/dlt/pyarrow-touching
  modules) + `pyright` (standard mode; editor-strict recommended) + `import-linter`
  (layered architecture). Run `make lint` for ruff; CI runs the rest. Every module uses
  `from __future__ import annotations` and type hints; relative imports are banned (TID252).
- **Config, not constants:** all connection info, credentials, bucket names, and endpoints
  come from `de_playground.config.settings` (pydantic-settings, read from `.env`). Don't
  hardcode hosts/keys/paths in modules.
- **Thin runners, pure logic:** transform/business logic lives in small *pure* functions
  (e.g. `gold.build_fact_sales`, `silver.conform`, `silver_cdc.collapse_changes`) that take
  and return DataFrames — easy to test. The `pipeline.py`/`run()` modules and the Airflow DAG
  only wire things together; they hold no business logic.
- **Shared helpers live in `common/`:** S3/bucket helpers in `common/lake.py`, the
  SparkSession factory in `common/spark.py`, the readiness-retry in `common/retry.py`. Don't
  re-implement these in a phase module — import them.
- **Secrets:** never commit real secrets. `.env` is gitignored; `.env.example` holds only
  obvious LOCAL-ONLY placeholders. See "Security" below.

## How to extend

**Add a source table.** Append a `TableSpec` to `extract/tables.py` (`WWI_TABLES`); add a
`SilverSpec` to `transform/silver.py` (`SILVER_TABLES`) with its snake_case primary key. For
CDC, add it to `sql/enable_cdc.sql` and re-run `make enable-cdc`. Temporal dimension tables
use `ValidFrom` as the cursor instead of `LastEditedWhen`.
> **Column-name contract:** dlt normalizes every source column to `snake_case` on the way
> into Bronze (`OrderID` → `order_id`, `LastEditedWhen` → `last_edited_when`). All downstream
> Silver/Gold code must reference the snake_case names, not the SQL Server originals. This is
> silent — there's no error if you use `OrderID`, it just won't match any column. CDC also
> captures only from enablement *forward*; the watermark/full load is the initial snapshot.

**Add a Gold mart.** Write a pure `build_*` function in `transform/gold.py`, wire it into
`build_gold()`, and add the table name to `transform/inspect_lake.py` (`_LAYERS["gold"]`).

**Add a service/phase.** Add it to `docker-compose.yml` under the right profile, add a
`make` target, and document it in `README.md`.

## Testing

`make test` runs DB-free unit tests (`tests/`) covering config, the lake/retry helpers, and
table specs — fast, no Docker/Java needed. The Spark transform logic (silver dedupe, gold
measures, CDC collapse, fact_invoices) is currently verified *ad hoc* against synthetic data
in local Spark, not in the committed suite (it needs Java/Spark). This is a known gap —
tracked in `docs/BACKLOG.md` (P2 "Spark unit tests"); see `docs/ARCHITECTURE.md` ("Deliberate
non-goals") for the rationale. When adding transform logic, verify it the same way and note
it in the PR.

## uv extras (avoid the churn)

Deps are split into extras (`process`=Spark, `eda`, `dev`); the FastAPI service moved out
to its own workspace member `api/pyproject.toml` (WS7). `uv sync
--extra X` installs X and *removes* the others — so switching phases can uninstall PySpark.
Use **`make sync-all`** to keep everything installed at once.

## Security

Least privilege is wired in for the local rig: the pipeline connects to SQL Server as the
SELECT-only `de_extract` login (`make create-app-login`), never `sa`; and to SeaweedFS as the
non-admin `app` S3 identity. `sa` and the S3 `admin` identity are used only by explicit setup
steps (`make restore`, `make enable-cdc`, `make create-buckets`). All defaults are local-only
placeholders. On Azure these become Entra ID + Key Vault + RBAC — see `docs/ARCHITECTURE.md`
("Deliberate non-goals") for the full local-vs-production trade-off list.

## When something breaks

Operational gotchas (service-not-running, JDK version, Apple-Silicon emulation, SeaweedFS/ES
readiness races, compose relative paths, `--build` staleness, bucket pre-creation, and the
Phase 5 platform ones — host-bridge DNS, registry name mismatch, stale `port-forward`s after a
deploy, task-pod OOM) all live in [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) as a
symptom → cause → fix runbook. Check there first.
