# AGENTS.md

Dense reference for AI coding agents. Avoids restating what's already in `CONTRIBUTING.md`,
`README.md`, and `docs/ARCHITECTURE.md` — points to them instead.

## Project purpose and architecture
- This repo is a local mirror of an Azure-style DE stack: SQL Server -> Bronze Parquet -> Silver/Gold Delta -> Elasticsearch -> FastAPI, orchestrated by Airflow (`README.md`, `docs/ARCHITECTURE.md`).
- Treat the system as **three planes**: batch/data (extract/transform/load), serving (API + ES), and control (Airflow DAG). Keep serving logic out of DAG code (`dags/wwi_pipeline.py`).
- The pipeline has two capture paths: watermark (`src/de_playground/extract/pipeline.py`) and CDC (`src/de_playground/extract/cdc.py`). CDC exists to propagate deletes that watermark misses.
- Elasticsearch is a **derived serving index**, rebuilt from Gold on each run; do not treat it as a source of truth (`src/de_playground/load/to_elasticsearch.py`).

## Where to put code
- Pure DataFrame transforms in `src/de_playground/transform/*.py` (examples: `build_fact_sales`, `build_fact_invoices`, `build_daily_agg`, `build_billed_daily_agg`, `silver.conform`, `silver_cdc.collapse_changes`). Pipeline runners and the Airflow DAG only wire calls — no business logic.
- **Cross-plane typed contracts in `src/de_playground/contracts.py`**: `FactSalesDoc` (the Gold/ES doc shape, Pydantic with `extra="forbid"`), `SalesSearchResult`, `INDEX_FACT_SALES`, `build_query` (the ES bool-query builder), `es_mapping()` (codegens the ES mapping from a Pydantic model). Both `load/to_elasticsearch.py` AND `api/main.py` import from here — the contract lives once. `api/` is allowed to import ONLY `de_playground.contracts`; import-linter's `api may only import de_playground.contracts` contract is what enforces this.
- Shared helpers in `src/de_playground/common/{lake,spark,retry,logging}.py`. Import them; do not re-implement.
- Config: call `get_settings()` from `src/de_playground/config.py` at-use (e.g. `settings = get_settings()` at the top of a function). The factory is `lru_cache`-backed so the cost is amortized; tests can `monkeypatch("...get_settings", return_value=fake)` for clean injection. No hardcoded hosts/keys/paths.
- Logging via `from de_playground.common.logging import get_logger`; call `set_correlation_id()` at the top of each runner's `run()` so a pipeline run's log lines share an id.
- Full conventions + how-to-extend in `CONTRIBUTING.md`.

## Developer workflow
- Python 3.11 + `make sync-all` (per-extra syncs uninstall siblings — and `--all-packages` is needed so api/ deps install too). Run order: `make extract` → `make transform` → `make index`; inspect with `make inspect LAYER=gold`. Behavior-preserving changes verify against `make regression` (per-commit) or `make accept` (cold-rebuild). CI checks: `make lint` + `make test` + `uv run mypy src` + `uv run pyright src api` + `uv run lint-imports`; the security job runs `pip-audit --strict --all-packages` + `gitleaks` + `lychee`. Full setup in `README.md` / `CONTRIBUTING.md`.

## Integration boundaries and networking
- Host-run Python commands use `localhost` defaults from `.env`; containerized services use Compose service names (`sqlserver`, `seaweedfs`, `elasticsearch`) on the `de` network.
- Airflow runs on the k3d cluster (Airflow 3, KubernetesExecutor — `platform/airflow*`), not in Compose. Its task pods reach the Compose data services via Docker Desktop's `host.docker.internal` bridge (the data plane stays in Compose; the control plane is on k8s).
- Spark has two execution modes: local (`make transform`, Ivy-resolved jars) vs cluster (`make cluster-transform`, jars baked in image + wheel via `--py-files`) (`src/de_playground/common/spark.py`, `jobs/transform_cluster.py`).

## Operational conventions (agent-specific)
- **Fail fast on missing infrastructure:** `ensure_bucket` in `src/de_playground/common/lake.py` raises if buckets don't exist — the pipeline's app identity can't create them (admin step is `make create-buckets`). Don't add fallback "create-if-missing" logic.
- **Silver/Gold are rebuilt with overwrite semantics** for repeatable reprocessing. New transforms must be idempotent on rerun.
- **dlt normalizes column names to snake_case** during extract (`OrderID` → `order_id`). All downstream Silver/Gold code must use the snake_case names. Map PK/cursor names accordingly when adding tables (`src/de_playground/extract/tables.py`).
- **Validate any Compose topology changes with `docker compose config`** before `up` (root `docker-compose.yml` uses the `include:` directive to assemble `compose/{core,spark,serving,observability}.yml`).
- **Failure-mode runbook** is `docs/TROUBLESHOOTING.md` — check there before diagnosing env errors.
