# Backlog

Single home for future work. Topical docs (`OBSERVABILITY.md`, `HANDOFF.md`) point here
instead of carrying their own scattered lists. Ordered roughly by priority.

## P1 — version upgrades (PAST EOL as of 2026-06-03)

Conservative versions chosen during the build have aged out — two are now **past EOL**, not
"due soon" (see `docs/HANDOFF.md`). All targets remain free/OSS. CI now gates lint+type+test
(`.github/workflows/ci.yml`), so do each upgrade behind that suite; they have breaking changes.
Recommended order: ES first (smallest blast radius), Spark second, Airflow third.

- **Elasticsearch/Kibana 8.14 → 8.19 (LTS) or 9.x** — EOL. Client constraint
  (`elasticsearch>=8.14,<9`) already resolves to 8.19.3, so server lags client. Smallest blast
  radius — bump server image first, run `make index` + Kibana smoke test.
- **Apache Spark 3.5 → 4.0/4.1** — 🔥 **52 days past EOL** (EOL 2026-04-12). Pair with
  `delta-spark` 4.x; update `spark/Dockerfile` jars, `pyproject` pin, and `metrics.properties`
  if needed. JDK 17 still works; 21 newly supported.
- **Airflow 2.11 → 3.x** — ✅ **done via Phase 5b** (validated end-to-end 2026-06-09): Airflow
  3.1.7 via the official Helm chart (1.19.0) with KubernetesExecutor on k3d (`platform/airflow*`,
  `platform/tofu/airflow.tf`; DAG migrated to `airflow.sdk` + standard-provider imports with a
  2.x fallback). The deprecated compose Airflow (`airflow/` dir, `up-airflow`/`down-airflow`/
  `airflow-logs` targets, `AIRFLOW_COMPOSE` var, README Phase 4 section) was **removed**
  2026-06-09.

## P2 — productionization (from `docs/HANDOFF.md`)

- **Structured logging** — replace 24 `print()` calls in 9 files (verified by audit) with the
  `logging` module + JSON formatter + per-run correlation ID. Inspect-script prints (`verify.py`,
  `inspect_lake.py`) should grow a `--json` flag so humans still get readable tables.
- **Spark unit tests** — add `tests/test_transforms_spark.py` covering the 4 pure transform
  functions (`build_fact_sales`, `build_fact_invoices`, `silver.conform`, `silver_cdc.collapse_changes`).
  Gate with a `pyspark` pytest marker so CI can opt in. Brings coverage from 4/15 → 8/15 modules.
- **`pytest-cov`** — add to the `dev` extra so `make test` reports coverage %.
- **ADRs** — formalize key decisions as immutable records under `docs/adr/` (MADR format).
  Decision rationale currently lives in `CHANGELOG.md` dated entries + `ARCHITECTURE.md`
  "Deliberate non-goals"; an ADR per decision would give one immutable file per choice.
- **Compose healthchecks** — only `sqlserver` has one today; add for ES, Kibana, SeaweedFS,
  Postgres so consumer services (Kibana waiting on ES) don't race cold-start.
- **`make check-env`** — small helper that diffs `.env` against `.env.example` and prints any
  missing keys (without echoing values). Cold-start validation on 2026-06-03 surfaced a stale
  `.env` (missing the 6 keys added during the identity-scoping work) which 403'd `make
  create-buckets`. A diff target would catch this for any future schema add.
- **Data quality gate / data contracts** — Great Expectations or Soda as an Airflow task between
  layers (freshness / volume / schema / distribution); fail the DAG on breach. + freshness SLAs/SLOs.
- **Data lineage** — OpenLineage emitters (Airflow + Spark) → Marquez locally / Purview on Azure.
- **Secrets vault** — move from static `.env` to a vault (Key Vault) for any non-local target.
- **IaC + cloud deploy target** — ⏳ *in progress via the Phase 5 platform track* (2026-06-03):
  local IaC (OpenTofu) + k3d + Helm chart (API) + Argo CD GitOps landed under `platform/`.
  Remaining increments:
  - **5b — Airflow 3 via official Helm chart on k3d** — ✅ done 2026-06-09 (KubernetesExecutor;
    absorbed the P1 Airflow EOL fix and retired the compose Airflow).
  - **5c — k3d-managed registry instead of `k3d image import`** (real push/pull), then CI
    builds the image + bumps the chart tag = full CD loop. ⏳ *in progress:* API done
    (registry in `k3d-config.yaml`; `make api-push`/`api-release` → Argo pull-based rollout,
    2026-06-09). **Next:** move the Airflow 3 image onto the same registry (its bump is a
    `tofu apply`, not Argo); optional `act`-driven release to mimic GH Actions locally.
  - **5d — a real cloud target** (AKS or Fabric/Databricks + ADLS) reusing the same OpenTofu
    workflow. docker-compose remains dev-only.
- **Scale testing** — validate on real distributed hardware (single-machine Spark hides shuffle cost).

## P3 — observability follow-ups (from `docs/OBSERVABILITY.md`)

- **Traces backend** — the OTel Collector currently logs traces to debug; add Jaeger or Tempo to
  persist them (one service + one exporter).
- **Tier 1 dlt run-trace → table** — persist dlt's per-table row counts / timings to a Bronze
  `_dlt_trace` table for cheap freshness/volume monitoring.
- **Airflow OTel metrics** — enable via `config.metrics`/`config.traces` in
  `platform/airflow-values.yaml` (Airflow 3 on the cluster); the OTel exporter is already in the
  custom image.

## P4 — data/feature enhancements

- **Index `fact_invoices` into Elasticsearch** alongside `fact_sales` (billed actuals searchable).
- **SCD2 dimensions** — slowly-changing-dimension (type 2) history for customer / stock-item dims.

## P5 — tooling / nice-to-have

- **Task runner** — optionally move `make` targets to a Python-native runner (`poethepoet` in
  `pyproject.toml`, or `nox` for test sessions) run via `uv`. Make is fine as-is; this is polish.
- **GitHub Actions caching** — add uv cache + ruff cache to `.github/workflows/ci.yml` to cut
  cold-install time. Currently no caching is configured.
- **GitHub issue / PR templates** — `.github/ISSUE_TEMPLATE/` + `PULL_REQUEST_TEMPLATE.md` for
  collaboration polish. Not needed for a solo PoC.
