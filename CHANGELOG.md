# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is pre-1.0, so dates
mark milestones rather than released versions.

## [Unreleased]

### Added
- **WS6 / diff-coverage gate at 80% of changed lines (2026-06-11):** CI's `quality` job
  now runs `pytest --cov=de_playground --cov-report=xml --cov-report=term` (total
  coverage reported, not gated). PRs additionally run
  `diff-cover coverage.xml --compare-branch=origin/<base> --fail-under=80` — each change
  must cover ≥80% of its own new/changed lines. Total threshold would be coverage
  theater (Spark suite can't run in default CI; legacy gaps would distort the number) —
  diff-cover is the 2026 consensus pattern for "rewards small well-tested commits
  without a flag-day backfill". `[tool.coverage.run] omit` keeps
  `transform.*`/`extract.cdc`/`extract.source` out of the default measurement (they're
  Spark/dlt-heavy; measured separately in the opt-in `pyspark` job). Current state: 57%
  total on the Java-free measurement, with the new contracts/config/extract.tables at
  100%; this WS5+WS6 PR itself reports 85% diff coverage. `.gitignore` adds
  `.coverage` + `coverage.xml`.

- **WS5 / pure-function + hypothesis + spark-marker tests (2026-06-11):** the pure-fn
  testing gap from BACKLOG / Finding 7 is filled. New files:
    - `tests/test_contracts.py` — `build_query` parametrize matrix (8 combos) + hypothesis
      property test ("any filter combination yields a structurally valid bool query");
      Pydantic model round-trips + `extra="forbid"` enforcement; `SalesSearchQuery` limit
      bounds.
    - `tests/test_load.py` — `to_actions` row count preservation, ISO-string date
      coercion, `_id` keyed to `order_line_id`, extra-field rejection, plus a hypothesis
      property test that ids round-trip 1:1.
    - `tests/test_verify.py` — `_build_report` OK / APPEND / DIFF status logic, no-source
      fallback, bucket-name passthrough (via mocked settings).
    - `tests/conftest.py` — session-scoped local-mode `spark` fixture (`local[2]`, no UI,
      2 shuffle partitions); uses `pytest.importorskip("pyspark")` so non-Spark jobs
      collect cleanly.
    - `tests/test_transforms_spark.py` — first three Spark-marked tests for
      `silver_cdc.collapse_changes` (latest-per-key, delete drops keys, change-meta
      cols stripped). More transforms (fact_sales, fact_invoices, silver.conform) to
      land as needed.
  `build_query` moved from `api/main.py` into `de_playground.contracts` so it's
  importable from `tests/` without an `api/` PYTHONPATH dance (api/main.py just
  re-imports it). `hypothesis>=6.0` + `pytest-cov>=5.0` added to the `dev` extra (cov is
  wired in WS6). `[tool.pytest.ini_options]` registers the `pyspark` marker and excludes
  it from the default run via `addopts = "-m 'not pyspark'"`. New opt-in `pyspark` CI
  job sets up JDK 17 (Temurin) and runs `pytest -m pyspark`. Default `quality` job stays
  Java-free. Result: 35 fast tests pass + 3 deselected (Spark) by default; opt-in job
  runs the 3 Spark tests in ~5s.

- **WS4 6c / mypy --strict (scoped) + pyright standard as CI gates (2026-06-11):**
  pyproject.toml `[tool.mypy] strict = true` with scoped overrides for
  `transform.*`, `extract.source`, `extract.cdc`, `extract.verify`,
  `load.to_elasticsearch` (the modules that work with untyped PySpark / dlt / pyarrow /
  delta-rs / elasticsearch internals — strict-checking them produces noise about third-
  party libs rather than real bugs). The explicit-contract boundaries (`config`,
  `common/lake`, `common/logging`, `common/retry`, `contracts`, `extract/tables`) stay
  unconditionally strict. `ignore_missing_imports = true` kept (untyped DE libs).
  `[tool.pyright]` runs in standard mode in CI alongside mypy; editor-strict recommended
  for live feedback. Both CI gates green: `mypy --strict src` (24 source files) and
  `pyright src api` (0 errors). Targeted noqa/type:ignore inline for the boto3-stubs +
  pyarrow.fs implicit-reexport interactions; one real pyright catch became a code change
  (api/main.py `es.get(id=...)` wants str, not int — cast on the call site).
  CONTRIBUTING.md "Conventions" line updated to reflect the now-true `mypy --strict`
  claim and the expanded ruff set + pyright + import-linter pipeline.

- **WS4 6b / typed DI seam + lake helpers + exception precision + py.typed (2026-06-11):**
  - `config.py` grows an `@lru_cache get_settings()` factory; `settings = get_settings()`
    stays as a backward-compat alias so existing consumers don't need touching. New code
    should call `get_settings()` so tests can override via `get_settings.cache_clear()`.
    Full constructor injection is P2 (WS9).
  - `common/lake.py` `s3_client()` and `pyarrow_s3()` get proper return types
    (`mypy_boto3_s3.S3Client`, `pyarrow.fs.S3FileSystem`) under `TYPE_CHECKING`. Turns
    the `boto3-stubs~=1.43.0` dep (kept in WS1) into actual enforcement.
  - New `common/lake.bronze_cdc_prefix_exists(table)` boto3 list-objects pre-check;
    `transform/silver_cdc.py` uses it instead of catching `AnalysisException` and
    string-matching `"PATH_NOT_FOUND"`/`"Path does not exist"` (Finding 6, brittle string
    flow control). Same observable "skipped — no CDC changes captured yet" behavior.
  - `extract/verify.py:79` `except Exception` narrowed to `(SQLAlchemyError, OSError)` —
    pyodbc/connection failures bubble as SQLAlchemyError subclasses (DBAPIError); OSError
    covers DNS / network unreachable. Source-vs-Bronze comparison stays best-effort.
  - `src/de_playground/py.typed` (PEP 561 marker) + minimal `__all__` in
    `src/de_playground/__init__.py` so downstream consumers get the typed surface.

- **WS4 6a / typed cross-plane contracts (2026-06-11):** new
  `src/de_playground/contracts.py` defines the shared Pydantic models — `FactSalesDoc`,
  `SalesSearchQuery`, `SalesSearchResult` — plus the single canonical `INDEX_FACT_SALES`
  string. Producer (`load.to_elasticsearch.to_actions`) and serving (`api.main`) both
  import them, so Finding 9's duplicated implicit contract (the same `"fact_sales"`
  string + document field set redeclared in two modules) is gone. `to_actions` now
  `FactSalesDoc.model_validate(row)`s every Gold row before yielding the bulk action;
  bad rows fail loud rather than landing as broken documents (`indexed: 231412, errors:
  0` against the WWI sample). FastAPI endpoints use `response_model=SalesSearchResult`
  /`FactSalesDoc` for automatic schema + validation. WS3 layers contract updated:
  contracts joins config at the leaf level (`config | contracts`). WS7's "api has no
  de_playground dep" was relaxed for this one module — api/pyproject.toml adds
  `de-playground` as a `[tool.uv.sources] de-playground = { workspace = true }` dep, and
  the api Dockerfile build context broadened to the repo root (`build: { context: ..,
  dockerfile: api/Dockerfile }`) so both packages can be installed. The serving plane
  still imports nothing from the pipeline runtime — only the schema. Verified: `make
  regression` empty; `/health` + 3 canonical queries byte-identical to Gate-0.

- **WS7 / uv workspaces; api/ promoted to its own pyproject (2026-06-11):** root
  `pyproject.toml` declares `[tool.uv.workspace] members = ["api"]`. New
  `api/pyproject.toml` owns the serving-plane deps (`fastapi`, `uvicorn[standard]`,
  `elasticsearch`, `opentelemetry-distro`, `opentelemetry-exporter-otlp`). The root `serve`
  extra is gone (deps moved out, killing the duplication between extras and the
  Dockerfile that Finding 11 called out — `provides-extras` now `["process", "eda",
  "dev"]`). `api/Dockerfile` rebuilt: pulls `uv` from the official distroless image then
  `uv pip install --system --no-cache .` against the workspace member — no inline pinned
  versions, single source of truth in `api/pyproject.toml`. `api/` declares **no**
  dependency on `de_playground` (serving-plane isolation, same boundary import-linter
  would enforce if api/ ever grew a package). `jobs/` stays in the core lib (it's a
  ~40-line spark-submit driver whose only dep IS de_playground[process]). Verified: `make
  regression` empty after `docker compose up -d --build api`; `/health` + 3 canonical
  queries identical to baseline.

- **WS3 / architecture enforced by import-linter (2026-06-11):** three contracts in
  `pyproject.toml` `[tool.importlinter]` machine-check the layering the docs assert.
  Layered architecture (`extract | transform | load` peers → `common` → `config`) with
  `exhaustive = true` — every new sub-package must be placed in the layer graph or the
  contract breaks, so drift is caught the moment it lands. Forbidden contracts:
  `common` cannot import any of the peers; `config` cannot import anything else in
  `de_playground`. New `import-linter>=2.0` in the `dev` extra; CI runs `uv run
  lint-imports` between mypy and pytest; pre-commit gets the upstream hook (v2.5). Gate
  proven to bite — a deliberately-injected `common.lake -> extract.tables` import is
  rejected with line numbers; reverted cleanly. Existing codebase passes all 3 contracts
  on day one (23 files, 40 dependencies analysed).

### Changed
- **WS2 / absolute imports + expanded ruff set (2026-06-11):** converted all 50 `from
  ..`/`from .` sites in `src/de_playground/` and `api/` to absolute (`from de_playground.X
  import Y`); enabled ruff's TID252 (`ban-relative-imports = "all"`) so new code can't
  regress. Expanded the `select` array with `TID, RUF, SIM, PTH, PT, LOG, G, RET, C4` —
  high-signal sets the source plan calls out (architecture, simplification, pathlib,
  pytest style, logging correctness, return-statement linting, comprehensions). Inline
  fixes for the in-tree hits: 3 RUF100 (unused noqa) auto-removed, 2 I001 (import sort)
  auto-fixed; G004 (f-string in log msg) per-file-ignored on `verify.py` +
  `inspect_lake.py` (their f-strings format the pretty-output line — the structured/JSON
  branch goes via `extra=`, so G004 there flags an intentional idiom, not a bug). Cross-
  module *layer* enforcement is import-linter's job (WS3), not ruff.

### Added
- **WS8 / supply-chain + CI hardening (2026-06-11):** Dependabot watching `pip` and
  `github-actions` ecosystems (weekly); a separate `security` CI job running `pip-audit
  --strict` (known-CVE deps via the full `uv sync --all-extras` env), `gitleaks-action`
  (secrets scan, with `.env.example`/`config.py` LOCAL-ONLY placeholders allowlisted in
  `.gitleaks.toml`), and `lychee-action` (markdown link check across all `**/*.md`); the
  same `gitleaks` hook added to pre-commit. Workflow itself hardened: top-level
  `permissions: contents: read` (widen per-job only where needed), every action SHA-pinned
  with a `# v<major>` comment (so Dependabot can bump). Ruff `select` extended with the
  `S` ruleset (flake8-bandit); 4 false positives noqa'd inline (S105 LOCAL-ONLY
  placeholders in `config.py`, S608 string-templated `text(...)` SQL that interpolates
  hardcoded `WWI_TABLES` schema/table names, not user input) and `S101` (`assert` in
  tests) per-file-ignored under `tests/`. Finally untracked the 6 committed `.idea/*`
  files (`.idea/` was already in `.gitignore` — they just predated it).

### Removed
- **WS1 / dependency hygiene (2026-06-11):** dropped three spurious entries from the
  *main* `pyproject.toml` `dependencies` array: `operators>=1.0.1` (an unrelated PyPI package
  imported nowhere — supply-chain smell), `psutil>=7.2.2` (no imports), and `uvicorn>=0.48.0`
  (a duplicate — uvicorn is already in the `serve` extra). Re-locked; venv reflects state.
  `boto3-stubs~=1.43.0` kept and earmarked for typed-boundary wiring in WS4. First step of
  `docs/PYTHON_HARDENING_PLAN.md`'s P1 series; behavior-preserving — `make regression` empty
  vs the Gate-0 baseline.

### Fixed
- **`inspect_lake` redirect-hang (2026-06-11):** added `os._exit(0)` at end of
  `inspect_lake.py` `__main__` block. `DeltaTable.to_pyarrow_dataset()` spawns non-daemon Rust
  threads in delta-rs, so a redirected invocation (`uv run python -m ... silver --json > file
  2>&1`) used to hang after writing the report — Python waits on the Rust threads. Pipe-to-
  consumer (`| tail`/`| jq`) masked this via SIGPIPE. The new `make baseline`/`make
  regression` oracle writes to a file before jq-stripping, so it surfaced the underlying bug.

### Changed
- **Doc-accuracy sweep (2026-06-09):** audited all 11 tracked `.md` files programmatically
  (every `make` command cross-checked against real targets, all path refs + internal links
  verified, stale-token scan). Fixes: `docs/HANDOFF.md` refreshed to reflect Phase 5 (local
  IaC/K8s/GitOps/CD now ✅; "managed *cloud* target" is the remaining gap; Airflow EOL resolved);
  `docs/ARCHITECTURE.md` project tree (dropped deleted `airflow/`, added `platform/` + `compose/`)
  + KubernetesExecutor compute-topology note + a platform row in the Azure mapping;
  `docs/TROUBLESHOOTING.md` pod_template entry → registry image ref; `CONTRIBUTING.md` runbook
  pointer → current platform gotchas. No dangling `make`/link/path references remain.
  Then swept **non-md** surfaces the same way: `platform/airflow/Dockerfile` header + `Makefile`
  `platform-stop` help (renamed-target / "imported images" phrasing), and `dags/wwi_pipeline.py`
  docstring + comments (k8s task pods reach data services via `host.docker.internal`, not compose
  service names on the `de` network; KubernetesExecutor task **pods**, not workers; Airflow 3
  backfill CLI is `airflow backfill create`, not `airflow dags backfill`; flagged the vestigial
  `PYTHONPATH=/opt/de_playground/src` as a no-op leftover from the volume-mounted compose era).

### Removed
- **Deprecated compose Airflow** (Phase 4): deleted the `airflow/` dir (Dockerfile +
  docker-compose.yml), the `up-airflow`/`down-airflow`/`airflow-logs` Make targets and the
  `AIRFLOW_COMPOSE` var, and the README Phase 4 section — superseded by Phase 5b (Airflow 3 on
  k3d), validated end-to-end 2026-06-09. Doc references in TROUBLESHOOTING/OBSERVABILITY/BACKLOG/
  AGENTS and the root compose comment updated to point at the cluster. The `dags/` package is
  unchanged (git-synced by the cluster). One-time host cleanup for the orphaned metadata/log
  volumes: `docker volume ls | grep airflow` then `docker volume rm <names>`.

### Added
- **Phase 5c — registry-based CD**: replaced `k3d image import` with a **k3d-managed registry**
  declared in `platform/k3d-config.yaml` (created + wired by `make platform-up`; host port 5111,
  not 5000 which macOS Control Center holds). **Both** images now pull from it, so nothing
  side-loads.
  - **API** → `registry.localhost:5111/de-playground-api:<git-sha>`; `api-push` (build+push, SHA +
    moving `latest`; refuses a dirty tree so the artifact matches its commit) + `api-release` (push
    → bump `values.yaml` tag → commit `[skip ci]` → push = the local CI stand-in for the
    **pull-based GitOps** loop; Argo CD reconciles to the committed tag).
  - **Airflow** → `registry.localhost:5111/de-playground-airflow3:<git-sha>`; `airflow3-push` +
    `airflow3-release` (push → bump both image tags in `airflow-values.yaml` → `tofu apply`). Same
    registry; the deploy is OpenTofu/Helm, **not** Argo — a deliberate two-pattern contrast.
  - Pull name is the bare `registry.localhost` (**no `k3d-` prefix** — SimpleConfig
    `registries.create` uses the `name:` verbatim, unlike the `k3d registry create` CLI; the
    truth is `cat /etc/rancher/k3s/registries.yaml` on a node). Push via `localhost:5111`, pull via
    `registry.localhost:5111` (same store, no `/etc/hosts` edit). `registry-ls` lists the catalog.
    Verified: both chart renders emit the wired pull ref, Makefile parses, configs valid. Cloud
    registry + GH-hosted CI doing the build/push is 5d.
- **Phase 5b — Airflow 3 on the cluster** (closes BACKLOG P1 Airflow EOL): official
  apache-airflow chart 1.19.0 (Airflow 3.1.7) with **KubernetesExecutor** on k3d, deployed by
  OpenTofu (`platform/tofu/airflow.tf`); custom image `platform/airflow/Dockerfile` (JDK17 +
  msodbcsql18 + pipeline venv with the de_playground wheel **baked in** — k8s ships artifacts,
  not mounts); DAGs **git-synced** from the repo's `dags/`; task pods reach the compose data
  services via `host.k3d.internal`. DAG migrated to Airflow 3 imports (`airflow.sdk` +
  standard-provider BashOperator) with a 2.x fallback. Values rendered + schema-validated
  against the real chart (catch: `images.pod_template` doesn't inherit `images.airflow` —
  task pods would have run the stock image). Compose Airflow (`airflow/`) is **deprecated**,
  removal tracked in BACKLOG P1. New targets: `airflow3-image`, `airflow3-ui` (:8082).
  - **5b follow-up (ephemeral-pod debugging):** remote task logging to SeaweedFS
    (`config.logging` → `s3://bronze/airflow-logs`; amazon provider added to the Airflow image;
    `aws_s3` JSON connection with SeaweedFS endpoint + path-style) so logs survive pod deletion
    (the "Could not read served logs" symptom). Bumped `apiServer.resources` (512Mi/1Gi) after
    OOMKills caused false task failures on the shared machine.
  - **Host bridge fix:** this k3d build doesn't inject `host.k3d.internal` (NXDOMAIN in pods),
    so all cluster→host data endpoints (`platform/airflow-values.yaml`, `platform/charts/api`,
    `k3d-config.yaml`) now use Docker Desktop's `host.docker.internal`. That was the real cause
    of extract task failures (DNS), separate from the api-server OOM.
  - **Transform task-pod OOM fix:** the `transform_silver_gold` task runs Spark in local mode
    *inside* the pod; with no limit the driver JVM sized `-Xmx` to ~¼ of the node and got
    OOM-killed on the shared Docker Desktop VM. Added `SPARK_DRIVER_MEMORY=2g` (the launch-time
    knob; `spark.driver.memory` is ignored in client mode) and `workers.resources` (req 2Gi /
    limit 3.5Gi, cpu 2) so KubernetesExecutor task pods get an explicit, scheduler-reserved
    budget. Values-only — `tofu apply`, no image rebuild. Rendered against the real chart.
  - **Restart recovery:** added `make platform-start`/`platform-stop` (`k3d cluster start/stop`,
    the correct verb after a reboot vs `platform-up`'s `create`) and a README "After a machine or
    Docker restart" section — the cluster + imported images survive a reboot, only port-forwards
    don't.
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
