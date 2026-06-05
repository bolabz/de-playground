# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is pre-1.0, so dates
mark milestones rather than released versions.

## [Unreleased]

### Added
- **Phase 5a — platform track** (`platform/`): k3d cluster config (1 server + 2 agents),
  Helm chart for the API (`platform/charts/api`, probes/resources/`host.k3d.internal` ES
  bridge; `helm lint` + `template` verified), OpenTofu root module (`platform/tofu`:
  namespaces + Argo CD via `helm_release`; `tofu validate` + `fmt` verified), Argo CD
  `Application` for GitOps (`platform/argocd/`, repoURL parameterized), and Make targets
  (`platform-up/down`, `api-image`, `platform-apply`, `api-deploy`, `argocd-app/ui`,
  `api-forward`, `ci-local` via act). OpenTofu over Terraform per the free/OSS rule (BUSL).
  Next increments tracked in BACKLOG P2: 5b Airflow-3-via-Helm, 5c registry, 5d cloud target.
- `.devcontainer/` for reproducible, any-machine dev environments.

## 2026-06-03 — second audit cycle + structured logging

### Added
- **Structured logging** (`src/de_playground/common/logging.py`): JSON formatter for
  non-TTY / production, pretty formatter for TTY / local; per-run `correlation_id` via
  `contextvars.ContextVar`; `set_correlation_id()` at each runner entrypoint; defensive
  namespace anchoring so `python -m de_playground.x` (which sets `__name__ == "__main__"`)
  still reaches the configured handler.
- `--json` flag on `verify.py` and `inspect_lake.py` for machine-readable inspection output.
- 5 `TROUBLESHOOTING.md` entries covering: stale `.env` 403s on `make create-buckets`,
  `make down` / `make nuke` not reaching profile-scoped services, `make up-serve` clobbering
  the spark-worker count, the README `q=cable` example returning empty, `uv venv` future
  `--clear` requirement, and the Homebrew JDK 17 vs `/usr/libexec/java_home` fallback.

### Changed
- Replaced 24 `print()` calls across 9 src files with structured `log.info(extra={...})`
  using `de_playground.common.logging.get_logger`.
- `Makefile`: `down` and `nuke` now pass `--profile all --profile observability --profile
  submit --remove-orphans` so they actually stop services in named profiles. `up-serve` and
  `up-all` pass `--scale spark-worker=2` so toggling profiles no longer drops a worker.
- `README.md`: search example `q=cable` → `q=USB` (WWI's catalog is novelty merch, not
  hardware); added a `Documentation` taxonomy section that classifies docs as stable
  reference vs. dated snapshots; clarified SQL Server admin-vs-pipeline login distinction.
- `docs/HANDOFF.md` refreshed and trimmed: status table reflects post-handoff reality
  (LICENSE/CI/pre-commit/devcontainer/compose-split all ✅); duplicated EOL versions and
  "remaining steps" content pointed to `BACKLOG.md`.
- `docs/AUDIT.md` migrated and removed: dated entries here; "deliberate non-goals" merged
  into `docs/ARCHITECTURE.md`; the doc itself deleted to eliminate the mixed-purpose
  decision-log / change-history / non-goals overlap.
- `api/main.py`: fixed pre-existing `B904` (`raise ... from err`).

### Validated
- Cold-start → teardown pipeline run (Python 3.11 venv recreated, `make up-ingest` →
  `restore` → `create-app-login` → `enable-cdc` → `up-process` → `create-buckets` →
  `up-serve` → `extract` → `extract-cdc` → `transform` → `index` → `inspect LAYER=gold`
  → `up-airflow` → trigger DAG → `down`). End-to-end ~5 min wall time.
- Post-migration smoke: `make extract` + `transform` + `index` emit JSON logs with a
  shared per-process `correlation_id`; `inspect --json` produces a single nested event.

## 2026-06-01 — first full audit

### Added
- `docs/ARCHITECTURE.md` (system design + 4 sequence flows + project structure),
  `docs/GLOSSARY.md`, `CONTRIBUTING.md`.
- Real least-privilege identities for the local rig: SELECT-only `de_extract` SQL login
  (scoped to `Sales` + `cdc` schemas; created by `make create-app-login`) and a non-admin
  `app` SeaweedFS identity. `sa` / S3 admin reserved for explicit setup steps only.
- `make create-buckets` admin step (buckets are no longer auto-created by the pipeline).

### Changed
- Consolidated `_s3_client` + `ensure_bucket` into `src/de_playground/common/lake.py`
  (the duplicate copy in `extract/pipeline.py` was missing the SeaweedFS readiness retry).
- Moved `mssql_url` from the extract runner to `config.py` as `settings.mssql_url`;
  deleted the unused `mssql_odbc_connstr` property.
- Removed `extract/verify.py`'s `_s3_filesystem` duplicate of `common.lake.pyarrow_s3`.
- Unified S3 + ES readiness loops onto `common/retry.py` (one helper, not two).
- `extract/cdc.py` and `extract/verify.py` now depend only on `config` + `common`, not on
  the sibling `extract/pipeline.py` runner — restoring the phases→common dependency
  direction.
- Refreshed `docs/ARCHITECTURE.md` project-structure block (was missing CDC, cluster-submit,
  Airflow, billed mart); added a CDC sequence flow and a Change-Tracking-vs-CDC glossary
  entry.

### Removed
- Redundant `make` targets (`inspect-gold` ≡ `inspect LAYER=gold`; `spark-image` was built
  implicitly by `up-process`).

## Milestones (build history)
- Phases 0–4 complete: foundation → dlt extract (Bronze) → PySpark medallion (Silver/Gold
  Delta) → Elasticsearch + FastAPI serving → Airflow orchestration.
- Added cluster-submit (standalone Spark), full SQL Server CDC (alongside the watermark),
  and a billed-revenue mart (`fact_invoices`).
- Engineering hygiene: `LICENSE` (MIT), GitHub Actions CI (`ruff` + `mypy` + `pytest`),
  `.pre-commit-config.yaml`, this changelog.
- `BACKLOG.md` (consolidated future work) and `TROUBLESHOOTING.md` (runbook).
- `docs/HANDOFF.md` (production-readiness snapshot) and `docs/OBSERVABILITY.md`.
- Observability stack (opt-in profile): OpenTelemetry Collector, Prometheus, Alertmanager,
  Grafana, exporters; container logs → Elasticsearch (ELK); FastAPI OTel-instrumented.
- Split `docker-compose.yml` into `compose/{core,spark,serving,observability}.yml` via
  the `include:` directive.

### Pins past end-of-life (tracked in `docs/BACKLOG.md` P1)
- Pinned Spark 3.5, Airflow 2.x, and Elasticsearch 8.14 are now past EOL (as of 2026-06) —
  Spark 4.x / Airflow 3.x / ES 8.19+ upgrades are firefighting, not "schedule soon".
