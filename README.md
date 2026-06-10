# de-playground

A local data-engineering playground that mirrors an enterprise **Azure** data stack. Every
local component is a deliberate stand-in for an Azure service, so the system design, data
flow, and durable concepts transfer when working in the cloud.

The pipeline is a **medallion ELT**: SQL Server (OLTP source) → incremental extract to
**Bronze** (raw Parquet) → PySpark transforms to **Silver** and **Gold** (Delta) →
Elasticsearch index → FastAPI serving, orchestrated by Airflow.

### Documentation

Docs fall into three groups. The rule that keeps them honest: **only `BACKLOG.md` and
`HANDOFF.md` describe what's "missing" or "TODO"** — everything else describes what *is*
(reference) or *what changed when* (`CHANGELOG.md`). That keeps the moving-target work in
one place and prevents drift creeping into stable reference docs.

**Stable reference** (how things *are*):
| Doc | What |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | diagrams, planes, sequence flows, project structure, deliberate non-goals |
| [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | terminology / acronyms |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | conventions + how to extend |
| [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) | monitoring/logging design + the Tier-2 stack |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | symptom → cause → fix runbook |

**Dated snapshots / forward work**:
| Doc | What |
|---|---|
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | production-readiness snapshot (industry standards comparison) |
| [`docs/BACKLOG.md`](docs/BACKLOG.md) | single home for forward work, P1–P5 |
| [`CHANGELOG.md`](CHANGELOG.md) | dated change history (Keep a Changelog) — decisions, refactors, releases |

## Prerequisites

This rig is set up for **Apple Silicon (32GB)**. You need:

- **Docker Desktop** running.
- **uv** (Python package/env manager).
- **Microsoft ODBC Driver 18 for SQL Server** on the host, for `pyodbc`:
  ```sh
  brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
  brew install msodbcsql18
  ```
- **JDK 17** on the host, for PySpark (Phase 2 only). Spark 3.5 supports Java 8/11/17 only —
  newer Java (21, 26, ...) will fail to start the JVM. Install 17 even if you have a newer
  default; the `make transform/silver/gold` targets auto-select it via `/usr/libexec/java_home`:
  ```sh
  brew install openjdk@17
  ```
  (No need to change your system default `java` — the Makefile pins JDK 17 just for Spark.)

> SQL Server has no native arm64 image, so the compose file pins `platform: linux/amd64`
> and it runs under emulation. This is expected and already confirmed working here.

## Quick start

```sh
# 1. Python env + config  (use Python 3.11 — PySpark 3.5 isn't tested on 3.13+/3.14)
uv venv --python 3.11
make sync-all                # all extras at once. NB: `uv sync --extra X` REMOVES other extras,
                             #   so per-extra syncs uninstall e.g. PySpark — prefer sync-all.
cp .env.example .env         # local-only placeholders; edit if you like. .env is gitignored.

# 2. Bring up the stack one plane at a time
make up-ingest               # Phase 1: SQL Server + SeaweedFS
make up-process              # Phase 2: + Spark (2 workers)
make up-serve                # Phase 3: + Elasticsearch, Kibana, FastAPI
# make up-all                # or everything at once (fine on 32GB)

# 3. One-time setup once the services are up
make restore                 # restore WideWorldImporters (+DW) from data/backups/
make create-app-login        # create the least-privilege de_extract login the pipeline uses
make create-buckets          # create the bronze/silver/gold buckets (admin S3 identity)

make ps                      # what's running
make down                    # stop (keeps data)   |   make nuke = stop + wipe volumes
```

> **Security model (local):** the pipeline connects as a SELECT-only `de_extract` SQL login
> and a non-admin `app` S3 identity — never `sa`/admin, which are reserved for the setup steps
> above. Credentials are local-only placeholders in `.env` (gitignored). See
> `docs/ARCHITECTURE.md` ("Deliberate non-goals") for the local-vs-production trade-offs and
> `CONTRIBUTING.md` to extend the project.

## Sample databases

Backups live in `data/backups/` (gitignored). `make restore` copies them into the
container and restores with `WITH MOVE` (the backups carry Windows paths that don't exist
on Linux). The script discovers each backup's logical file names dynamically, so it also
handles the in-memory OLTP filegroup correctly.

| Backup | Database | Role |
|---|---|---|
| `WideWorldImporters-Full.bak` | WideWorldImporters | **OLTP source** — Phase 1 extracts from this |
| `WideWorldImportersDW-Full.bak` | WideWorldImportersDW | star-schema warehouse — **reference only** ("answer key") |

> In-Memory OLTP is supported on SQL Server on Linux, so the OLTP restore works as-is.
> FILESTREAM (a different feature) is not — WWI doesn't depend on it.

Run `make help` to see all targets.

> After a Docker Desktop or machine restart, only `sqlserver` comes back on its own (it has a
> restart policy). Re-run the relevant `make up-*` to bring the lake and other services back
> up before running extracts/transforms — a `Connection refused` to `localhost:8333` (SeaweedFS)
> or `:9200` (Elasticsearch) almost always means that service just isn't running. If you also
> run the Phase 5 cluster, see [After a machine or Docker restart](#after-a-machine-or-docker-restart)
> for the full recovery order (compose **and** k3d).

## Service URLs

A service is only reachable once the profile that owns it is up. If you ran only
`make up-ingest`, the `process`/`serve` URLs will (correctly) refuse connections.

| Service | URL | Needs | Notes |
|---|---|---|---|
| SeaweedFS filer | http://localhost:8888 | `up-ingest` | browse the lake's files (web UI) |
| SeaweedFS S3 API | http://localhost:8333 | `up-ingest` | **not browsable** — S3 protocol, requires credentials. A bare `GET /` returning `AccessDenied` means it's working. Code uses `s3a://<bucket>` with the poc keys. |
| SQL Server | localhost:1433 | `up-ingest` | source — admin `sa` for setup/PyCharm (`.env` password); pipeline uses SELECT-only `de_extract` |
| Spark master UI | http://localhost:8080 | `up-process` | watch stages/shuffles |
| Elasticsearch | http://localhost:9200 | `up-serve` | derived serving index |
| Kibana | http://localhost:5601 | `up-serve` | dashboards |
| FastAPI | http://localhost:8000/docs | `up-serve` | auto Swagger UI — **stub until Phase 3** (won't serve yet) |

Use `make ps` to see what's actually running right now.

## Build phases

| Phase | What | Status |
|---|---|---|
| 0 | Foundation: compose, pyproject, scaffold, this README | ✅ done |
| 1 | dlt incremental extract: SQL Server → Bronze | ✅ done |
| 2 | PySpark: Bronze → Silver → Gold (Delta) | ✅ done |
| 3 | Elasticsearch load + FastAPI serving | ✅ done |
| 4 | Airflow DAG orchestration | ✅ done |
| 5a | Platform track: k3d + OpenTofu + Helm (API) + Argo CD + act | ✅ built |
| 5b | Airflow 3 via official Helm chart on k3d (closes the Airflow EOL item) | ✅ built |
| 5c | k3d-managed registry + `make`-driven build/push/tag-bump → Argo CD pull-based CD (API) | ✅ built |

## Extract: SQL Server → Bronze (Phase 1)

With `up-ingest` running and the databases restored:

```sh
uv sync          # picks up the Phase 1 deps (dlt, sqlalchemy, boto3, ...)
make extract     # uv run python -m de_playground.extract
```

This pulls four Sales tables (`Orders`, `OrderLines`, `Invoices`, `InvoiceLines`) from
WideWorldImporters and lands them as Parquet in `s3://bronze/wwi/<table>/` on SeaweedFS.
It creates the `bronze` bucket if missing.

**Incremental + idempotent.** Each table is loaded on a high-watermark cursor
(`LastEditedWhen`), and dlt persists the max value seen as pipeline state (synced to the
bronze bucket, not held in the job). Re-running pulls only rows newer than the watermark;
the primary key dedupes rows sitting exactly on the boundary. So running `make extract`
twice with no new source data writes no new rows — that's the idempotency guarantee.

Verify the landed files via the SeaweedFS filer (http://localhost:8888) under `bronze/wwi/`,
or check row counts:

```sh
make counts      # reads Bronze Parquet from SeaweedFS, compares to the SQL Server source
```

`make extract` also prints per-table row counts at the end of each run. A second run with no
new source rows reports 0 new rows (idempotency). `make counts` status column: `OK` = Bronze
matches source, `APPEND` = Bronze has more (expected after re-runs, since Bronze is raw and
append-only).

> Requires the ODBC Driver 18 on the host (see Prerequisites). The extract connects from
> your machine to SQL Server on `localhost:1433`.

## Change Data Capture (alongside the watermark extract)

The `LastEditedWhen` watermark catches inserts/edits but **misses deletes** (a deleted row's
timestamp never changes, so it lingers in Bronze/Silver forever). SQL Server **CDC** captures
every insert/update/delete from the transaction log into `cdc.*_CT` change tables. This path
runs *alongside* the watermark extract so you can compare them.

> CDC needs **SQL Server Agent** — the `sqlserver` service now sets `MSSQL_AGENT_ENABLED=true`,
> so recreate it once: `docker compose up -d sqlserver`. CDC also only captures changes from
> enablement *forward* (it doesn't backfill existing rows) — the full/watermark extract is your
> initial snapshot; CDC supplies the deltas. This "snapshot + stream" split is the same pattern
> Debezium / ADF / Fabric mirroring use.

```sh
make enable-cdc          # one-time: sp_cdc_enable_db + enable the 4 Sales tables (idempotent)
make create-app-login    # re-run so de_extract gets SELECT on the now-existing cdc schema
make extract-cdc         # change tables -> bronze/wwi_cdc/<table> (append feed, hex-LSN watermark)
make silver-cdc          # collapse the feed -> silver/wwi_cdc/<table> (latest per key, deletes applied)
```

**See the difference** — delete a row in SQL Server, then re-run both paths:

```sql
DELETE FROM Sales.OrderLines WHERE OrderLineID = 1;   -- in PyCharm / sqlcmd
```
```sh
make extract && make silver          # watermark path: the row STAYS (delete invisible)
make extract-cdc && make silver-cdc  # CDC path: the row is GONE from silver/wwi_cdc
make inspect LAYER=silver            # compare counts/rows between the two prefixes
```

The CDC Bronze carries three change-metadata columns — `change_lsn` (hex, the watermark),
`change_seqval`, `change_operation` (1=delete, 2=insert, 3=update-before, 4=update-after). Silver
keeps the latest change per key (after-image wins over before-image) and drops keys whose latest
op is a delete. Maps to Azure SQL CDC / Synapse / Fabric.

## Transform: Bronze → Silver → Gold (Phase 2)

Needs a JDK (see Prerequisites) and the `process` deps. Runs PySpark in **local mode** — it
does not require the docker Spark cluster (`up-process`); that cluster is an optional
"watch it run distributed" exercise. The transforms read/write SeaweedFS over S3A.

```sh
make sync-all              # ensures pyspark + delta-spark are present (first run also Ivy-fetches jars)
make transform             # Silver then Gold   (or: make silver / make gold)
```

What it builds, all as **Delta** tables on SeaweedFS:

- `silver/wwi/<table>` — one row per primary key, the latest by `last_edited_when`
  (Bronze is append-only raw; Silver is the deduped/conformed truth). Rebuilt from Bronze.
- `gold/wwi/fact_sales` — **ordered** demand: order-line grain, orders joined onto lines, with
  revenue measures (`extended_price`, `tax_amount`, `line_total`), partitioned by
  `order_year`/`order_month`.
- `gold/wwi/agg_sales_daily` — daily ordered roll-up (orders, lines, quantity, revenue).
- `gold/wwi/fact_invoices` — **billed** actuals: invoice-line grain, invoices joined onto
  invoice lines, the same revenue measures plus `line_profit` (invoices carry cost; orders
  don't) and an `is_credit_note` flag, partitioned by `invoice_year`/`invoice_month`.
- `gold/wwi/agg_billed_daily` — daily billed roll-up incl. profit. Ordered-vs-billed is the
  classic demand-vs-actuals comparison.

While a job runs, open the Spark UI at http://localhost:4040 to watch stages and shuffles
(the daily group-by is a shuffle). First run is slow — Ivy fetches the Delta + S3A jars once.

Inspect the Gold output (row counts, partitions, sample rows, revenue summary):

```sh
make inspect LAYER=gold   # reads Delta with delta-rs — no Spark/JVM, returns instantly
```

## Run the transforms on the Spark cluster (optional)

Phase 2 normally runs in local mode (`make transform`). To instead feel *distributed*
execution — submit to the standalone cluster and watch tasks spread across workers:

```sh
make cluster-transform   # builds the wheel, ensures the cluster + lake are up, then submits
```

(`cluster-transform` brings up the `process` stack itself — seaweedfs, master, 2 workers — so
you don't need a separate `make up-process`. The first run builds the custom Spark image,
downloading ~300MB of jars once.)

Open the master UI at http://localhost:8080 to watch the application register and its tasks
distribute across the workers; the per-application UI (linked from there) shows stages/shuffles.

How it differs from local mode:

- **Jars are baked into the image** (`spark/Dockerfile`) instead of Ivy-downloaded, so every
  executor has Delta + S3A on its classpath.
- **Your code reaches the cluster via `--py-files`** — `make wheel` builds
  `de_playground-*.whl` and spark-submit ships it to the driver and executors. (These transforms
  are pure DataFrame ops, so executors don't actually import it — but that's the mechanism
  you'd need the moment you add a Python UDF.)
- **Endpoints are service names**, not `localhost`: inside the `de` network the driver talks to
  `spark://spark-master:7077` and `http://seaweedfs:8333`.

> Honest caveat: on one laptop this teaches the *mechanics* (image build, submit, task
> distribution, packaging) but not the real cost of a network shuffle — all "nodes" share your
> machine. The muscle memory transfers; the performance lesson needs real hardware.

## Serve: Elasticsearch + FastAPI (Phase 3)

Bring up the serving plane, then index Gold into Elasticsearch:

```sh
make up-serve    # Elasticsearch (:9200), Kibana (:5601), FastAPI (:8000) — give ES ~30s
make sync-all    # ensures the elasticsearch client is present
make index       # bulk-loads gold/wwi/fact_sales into the `fact_sales` ES index
```

The indexer reads Gold via delta-rs and recreates the `fact_sales` index each run (it's a
**derived** store, rebuilt from Gold — never a source of truth), keyed by `order_line_id`.

Then hit the API at http://localhost:8000/docs (auto Swagger UI):

```sh
curl 'http://localhost:8000/health'
curl 'http://localhost:8000/sales/search?q=USB&limit=5'    # WWI sells novelty items: USB drives, mugs, shirts
curl 'http://localhost:8000/sales/search?customer_id=1&min_total=100'
curl 'http://localhost:8000/sales/501'
```

`/sales/search` does full-text on the line `description` (inverted index) plus optional
`customer_id` and `min_total` filters — the serving plane answers fast because it hits the
read-optimized index, never the lake or SQL Server. The WWI catalog is novelty merch
(`USB`, `mug`, `shirt`, `joke`, `bubble wrap` all match thousands of lines); `cable`/`hardware`
terms return zero hits — those products don't exist in the sample data.

**Kibana** (http://localhost:5601): create a data view on index `fact_sales` (time field
`order_date`) to explore/visualize — the local stand-in for Power BI. WWI orders run
~2013–2016, so widen the Discover time picker or you'll see "No results".

Kibana data views, visualizations, and dashboards are saved objects stored in Elasticsearch
(they survive restarts via the `es-data` volume, but a `make nuke` wipes them). To make them
reproducible, snapshot them to a committed file:

```sh
make kibana-export    # -> kibana/saved_objects.ndjson  (commit this)
make kibana-import     # re-create them after a reset (overwrite=true)
```

## Orchestrate: Airflow

Airflow is the **control plane** — it schedules and triggers the pipeline (extract → transform
→ index) with retries and backfills. It runs on the **k3d cluster** as Airflow 3 with the
KubernetesExecutor; see [Airflow 3 on the cluster (Phase 5b)](#airflow-3-on-the-cluster-phase-5b)
for how to build the image, deploy it, and trigger the `wwi_pipeline` DAG. (The original
Phase 4 ran Airflow 2.x in a separate compose file; that was retired when 5b closed the
Airflow 2.x EOL item.)

## Observability (metrics, logs, traces)

An opt-in `observability` profile adds the Tier-2 stack from `docs/OBSERVABILITY.md`, unified
through OpenTelemetry. It runs alongside any phase (targets that are down just show DOWN):

```sh
make up-serve            # something to observe (ES is also the log store)
make up-observability    # OTel Collector + Prometheus + Alertmanager + Grafana + exporters
```

| UI | URL | What |
|---|---|---|
| Grafana | http://localhost:3001 | dashboards (admin/admin); Prometheus + Elasticsearch-logs datasources |
| Prometheus | http://localhost:9090 | metrics + targets + alert rules |
| Alertmanager | http://localhost:9093 | firing alerts (add a Slack webhook to notify) |
| Kibana | http://localhost:5601 | **logs**: create a data view on `otel-logs` (the ELK "L") |

See [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) for the design (3+1 pillars, Tier 1/2/3
plan), the per-component telemetry map, the Azure-managed equivalents, and the Docker-Desktop
Mac caveats (cAdvisor/node-exporter measure the Linux VM, container-log tailing assumes
`json-file` driver).

## Platform track: Kubernetes + IaC + GitOps (Phase 5)

Practice the production deployment lifecycle locally — a real k8s cluster (k3d), real IaC
(OpenTofu — the MPL-2.0 fork of Terraform, per the free/OSS rule), a Helm chart, GitOps CD
(Argo CD), and local CI (act). The division of labor mirrors industry: **OpenTofu provisions
the platform** (namespaces, Argo CD); **Argo CD deploys the apps** from git.

```sh
brew install k3d kubectl helm opentofu act    # prereqs, all free/OSS

make platform-up       # k3d cluster (1 server + 2 agents) + a managed image registry
make api-push          # build the API image + push it to the cluster's registry (Phase 5c)
make platform-apply    # OpenTofu: tofu init && apply -> namespaces + Argo CD
make api-deploy        # deploy the API chart with helm (the pre-GitOps loop)
make api-forward       # -> http://localhost:8001/docs (served from the cluster!)
```

The in-cluster API reaches Elasticsearch in your compose stack via k3d's host bridge
(`host.docker.internal`) — the hybrid is deliberate while the data services stay in compose.

**GitOps (once the repo has a remote):** set `repoURL` in `platform/argocd/api-application.yaml`,
then `make argocd-app`. Argo CD now keeps the cluster synced to `platform/charts/api` — push a
chart change to git and watch it roll out (`make argocd-ui` → http://localhost:8443).
**Login:** user `admin`; the password is generated by the chart at install time and lives in
the `argocd-initial-admin-secret` k8s secret — `make argocd-password` prints both. Change it
after first login (UI → User Info). `prune` + `selfHeal` are on: git is the source of truth,
manual drift gets reverted.

**Local CI:** `make ci-local` runs the GitHub Actions workflow in Docker via act.

> Run the cluster *instead of*, not alongside, the full compose stack if memory gets tight.
> Teardown: `make platform-down` (the compose stack and all data are untouched).

### Airflow 3 on the cluster (Phase 5b)

Airflow 3 (chart default 3.1.7) via the **official Helm chart** with **KubernetesExecutor** —
every task runs as its own pod, DAGs git-sync from this repo's `dags/` folder (push to `main`
= DAG update), and the pipeline code is **baked into the image** (on k8s, code ships as an
artifact, not a mount). This closes the Airflow 2.x EOL item and **replaced** the old compose
Airflow, which was removed (2026-06-09) — orchestration now lives entirely on the cluster.

```sh
make airflow3-image     # wheel -> docker build (platform/airflow/Dockerfile) -> k3d import
make platform-apply     # tofu adds the airflow namespace + the official chart release
kubectl -n airflow get pods -w    # first boot: migrations job, then components come up
make airflow3-ui        # -> http://localhost:8082  (admin / admin, LOCAL-ONLY)
```

Unpause + trigger `wwi_pipeline` and watch `kubectl -n airflow get pods -w`: each task
materializes as a pod (extract → transform → index), runs, and terminates — that's
KubernetesExecutor. Task pods reach the compose data services via `host.docker.internal`
(values must match your `.env`). Code changes need `make airflow3-image` again (the image is
the artifact); DAG-only changes just need a push.

How the DAG executes work (design notes):

- The DAG file is **thin** — only task wiring/schedule/retries; logic stays in `de_playground`.
- Each task is a `BashOperator` calling the same `python -m de_playground.*` entrypoints you run
  by hand, via an **isolated pipeline venv** baked into the image — keeping the pipeline's
  dependency stack (SQLAlchemy 2.x, PySpark, delta-spark, ODBC) separate from Airflow's own.
- Transform runs Spark in **local mode inside the task pod** (the image has a JDK); its driver
  heap is capped via `SPARK_DRIVER_MEMORY` and the pod has a reserved budget (`workers.resources`
  in the values) so it can't OOM the shared Docker Desktop VM.

> Honest caveat: in real enterprise Airflow / Azure Data Factory, the control plane *triggers
> external compute* (e.g. Databricks) rather than running it in the task pod. Running Spark
> in-pod here keeps the rig to one image — simpler to run solo. The orchestration concepts (DAGs,
> dependencies, retries, scheduling, KubernetesExecutor's pod-per-task) transfer; the in-pod
> execution topology is the part you'd do differently in the cloud.

### Registry-based CD (Phase 5c)

`k3d image import` side-loads an image straight into the cluster — fine for dev, nothing like
production. 5c replaces it with a real **container registry** and closes the CD loop: a release
**builds, pushes, bumps the chart's image tag, and commits** — then **Argo CD pulls and rolls it
out**. That's the production shape (ACR/GHCR + GitOps), local.

The registry is **k3d-managed** and declared in `platform/k3d-config.yaml`, so `make platform-up`
creates it and wires the cluster to pull from it. It has two names for the same store: you push
from the host to `localhost:5111`, the kubelet pulls via `registry.localhost:5111` (only the repo
path matters, so no `/etc/hosts` edit on macOS). Note the name has **no `k3d-` prefix** —
SimpleConfig `registries.create` uses the `name:` verbatim (unlike the `k3d registry create` CLI);
the wired name is whatever `cat /etc/rancher/k3s/registries.yaml` shows on a node. Images are tagged with the **git short SHA**
(immutable, traceable) plus a moving `:latest`.

```sh
make api-release        # build -> push (sha + latest) -> bump platform/charts/api/values.yaml -> commit + push
make argocd-ui          # watch Argo CD sync the new tag and roll the Deployment (http://localhost:8443)
make registry-ls        # what's in the registry (catalog + de-playground-api tags)
```

`make api-release` is the **local stand-in for a CI job** (`make api-push` is just the build+push
half). The chart's `image.tag` in `values.yaml` is the **GitOps record of what's deployed** —
Argo reconciles the cluster to it; the rollout is *pull-based*, not a `helm upgrade`. Release from
a clean tree: the image is tagged with `HEAD`'s SHA, so `api-push` refuses to run with uncommitted
changes (otherwise the artifact wouldn't match the commit it claims to be).

> A cloud-hosted GitHub Actions runner can't reach a `localhost` registry — that's why the CI step
> runs locally here (via `make`, or `act`). A real registry GitHub can push to is **Phase 5d**
> (cloud). The Airflow 3 image still uses `k3d image import`; moving it onto this registry is the
> next 5c step (its deploy is a `tofu apply`, not Argo — a parallel path).

## After a machine or Docker restart

A reboot stops every container. **Nothing is lost** — compose volumes (SQL Server, SeaweedFS
buckets, ES indices) and the k3d cluster's state survive — but services come back **stopped**
and the foreground `port-forward`s die. Recovery is restart, not rebuild: you do **not** re-run
`make restore` / `create-buckets`, `tofu apply`, or any `*-image` build. Bring things back in
dependency order:

```sh
# 0. Make sure Docker Desktop is running first (the whale icon is steady, not animating).

# 1. Data stack (compose). Lean set for the cluster track:
make up-data            # SQL Server + SeaweedFS + Elasticsearch
# ...or `make up-serve` / `make up-all` if you want Spark/Kibana/FastAPI on the host too.

# 2. The k3d cluster — START the existing one, do NOT create a new one:
make platform-start     # k3d cluster start de-playground   (NOT `make platform-up`)
kubectl -n airflow get pods -w   # wait for Argo CD + Airflow pods to go Running again

# 3. Re-open the port-forwards you want (each runs in the foreground, so use separate terminals):
make argocd-ui          # http://localhost:8443   (admin / `make argocd-password`)
make airflow3-ui        # http://localhost:8082   (admin / admin)
make api-forward        # http://localhost:8001/docs
```

Why this works: the k3d nodes (and the managed registry) are containers whose filesystem and the
cluster's etcd state persist across stop/start, so Kubernetes simply reschedules the Argo CD,
Airflow, and API workloads when the cluster starts — no IaC re-apply, no image re-push. The only
things that genuinely don't survive a restart are the `port-forward` processes (they're host-side
tunnels), which is why step 3 is always needed.

> A *restart* keeps the registry's images; a full *recreate* (`platform-down` → `platform-up`)
> gives a fresh empty registry, so re-run `make api-release` (API) and `make airflow3-image`
> (Airflow) after recreating.

> **`make platform-up` vs `make platform-start`:** `platform-up` runs `k3d cluster create` and
> will **fail** if the cluster already exists (it does, after a reboot — restart deletes nothing).
> Use `platform-start` to wake the existing cluster; reserve `platform-up`/`platform-down` for
> first-time creation and full teardown. `make platform-stop` is the clean way to free RAM
> without losing the cluster (e.g. to run the full compose stack for a while).

> **If you only run compose** (Phases 0–4, no cluster): just step 1 — re-run the `make up-*`
> for the planes you need. There's no cluster to start.

## Layout

`src/de_playground/` is the importable Python package (extract / transform / load /
common / config); `dags/`, `api/`, `spark/`, `platform/`, `sql/`, `tests/`, `notebooks/`,
`compose/` are tooling and service directories. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#project-structure) for the full annotated tree.

