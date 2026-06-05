# Troubleshooting

Symptom → cause → fix for issues actually hit running this rig. Most "errors" are environment
state (a service not up, wrong Java, a readiness race), not code.

## Stack won't start / connection refused

**`Cannot connect to the Docker daemon at .../docker.sock`**
Docker Desktop isn't running. Start it (`open -a Docker`), wait for the whale icon to settle,
confirm with `docker info`, then retry.

**`Connection refused` to `localhost:8333` (SeaweedFS) or `:9200` (Elasticsearch)**
That service isn't running. Only `sqlserver` auto-restarts after a Docker/machine restart (it
has a restart policy); the rest don't. Re-run the relevant `make up-*` (e.g. `make up-ingest`
for the lake, `make up-serve` for ES). Containers were likely brought down by a restart.

**`make up-serve` shows the API but `localhost:8000/docs` refuses**
Stale `api` image (e.g. built before the app existed). `make up-serve` now uses `--build`;
or force it: `docker compose --profile serve up -d --build api`. Check `docker compose logs api`.

## SQL Server / databases

**Restore/connect times out right after `make up-ingest`**
SQL Server runs under x86 emulation on Apple Silicon and is slow to accept connections on first
boot (~30–90s). `make restore` waits; if connecting manually, give it a minute. The compose
healthcheck gates readiness on recreate.

**`Cannot open backup device ... Operating system error 5 (Access is denied)`**
The `.bak` copied into the container isn't readable by the `mssql` user. `make restore` now
`chmod`s the backups dir as root; re-run `make restore`.

**Restore fails with Windows paths (`D:\Data\...`)**
The backups were taken on Windows. `sql/restore.sql` handles this with dynamic `WITH MOVE`;
use `make restore` rather than a hand-written `RESTORE`.

**CDC: `make extract-cdc` returns 0 rows**
Expected on first run — CDC only captures changes made *after* it was enabled. Make a change
(`UPDATE`/`DELETE` a Sales row) and re-run. Also ensure SQL Agent is on (`MSSQL_AGENT_ENABLED=true`,
recreate `sqlserver`) so the capture job runs.

**CDC: `make silver-cdc` errors `PATH_NOT_FOUND ... wwi_cdc/<table>`**
A table had no captured changes, so no Bronze folder exists. The current code skips missing
tables — make sure you're on the latest `silver_cdc.py`.

## Spark / transforms

**`make transform` fails: `unsupported Java` / JVM errors**
Spark 3.5 supports Java 8/11/17 only (not 21/26). Install JDK 17 (`brew install openjdk@17`);
the `transform`/`silver`/`gold` targets auto-select it.

**`ModuleNotFoundError: No module named 'pyspark'`**
`uv sync --extra serve` (or any single-extra sync) uninstalled the `process` extra. Use
`make sync-all` to keep all extras. (Use a Python 3.11 venv — PySpark 3.5 isn't tested on 3.13+/3.14.)

**Cluster submit can't reach the lake / `seaweedfs` name won't resolve**
`make cluster-transform` brings the `process` stack up first; ensure SeaweedFS is running and
on the `de` network. Inside containers, use service names (`seaweedfs:8333`), not `localhost`.

## Lake / buckets

**`bucket 'bronze' does not exist`**
The pipeline's app S3 identity can't create buckets by design. Run `make create-buckets` once
(admin identity).

**`make create-buckets` fails with `403 Forbidden` (HeadBucket)**
Stale `.env` — your local file predates the current schema and is missing the S3 admin keys
(or has an old `pocaccesskey` value that doesn't match what SeaweedFS is configured for).
SeaweedFS logs `InvalidAccessKeyId: attempted key '<key>' not found`. Fix:
`diff <(grep -E "^[A-Z_]+=" .env | sed 's/=.*//' | sort) <(grep -E "^[A-Z_]+=" .env.example | sed 's/=.*//' | sort)`
to find missing keys, then refresh: `cp .env.example .env` and re-add any custom values.
(Tracked: a `make check-env` target would auto-detect this; see BACKLOG.)

## Make / Compose

**`make: unrecognized option '--scale'`**
`--scale` is a `docker compose` flag, not a `make` flag. `make up-process` already scales
workers; to control it use `docker compose --profile process up -d --scale spark-worker=N`.

**`make down` / `make nuke` leaves containers running**
Fixed (2026-06-03) — both targets now pass `--profile all --profile observability --profile submit
--remove-orphans` so they reach services that live in named profiles. If you're on an older
checkout that hasn't picked up the fix, the manual incantation is:
`docker compose --profile all --profile observability --profile submit down -v --remove-orphans`.

**Spark worker count drops from 2 → 1 after `make up-serve`**
Fixed (2026-06-03) — `up-serve` and `up-all` now pass `--scale spark-worker=2` so they don't
clobber the count set by `up-process`. Without the flag, every `up` call without `--scale`
defaults the replica count back to 1.

**`/sales/search?q=cable` returns 0 results**
Not a bug — WWI's catalog is novelty merch (USB drives, mugs, shirts, joke items, bubble wrap).
Use `q=USB`, `q=mug`, `q=shirt`, or `q=joke` for examples that return data. The README example
has been updated.

**`unable to prepare context: path ".../airflow/airflow" not found`** (or `compose/...`)
Compose resolves relative paths against the compose file's directory. The `airflow/` and
`compose/*.yml` files use `../` for repo-root paths and `build: .`/`../<dir>` accordingly.
Validate any compose change with `docker compose config` before `up`.

**Airflow DAG doesn't appear in the UI**
The scheduler's DAG folder must be mounted to the real `dags/` (the airflow compose uses
`../dags`). Check `docker compose -f airflow/docker-compose.yml exec airflow-scheduler airflow dags list`
and `... list-import-errors`.

## Observability

**Prometheus target `spark-master` shows DOWN**
Expected unless the `process` profile is running — observability runs alongside any phase, and
down targets just show DOWN (that's what the `TargetDown` alert demonstrates).

**No logs in Kibana / cAdvisor metrics look wrong on Mac**
The OTel filelog receiver needs Docker's default `json-file` log driver; create a Kibana data
view on `otel-logs`. On Docker Desktop, cAdvisor/node-exporter measure the Linux VM, not macOS.

## Python / venv

**`uv venv --python 3.11` warns: "In the future, uv will require `--clear` to replace it"**
The implicit overwrite of an existing `.venv` is being deprecated. When uv removes it, the
documented command will silently fail. Use `uv venv --python 3.11 --clear` when recreating an
existing venv, or remove `.venv` first.

**`/usr/libexec/java_home -v 17` fails but `brew list openjdk@17` shows it installed**
Homebrew JDKs aren't automatically registered in `/Library/Java/JavaVirtualMachines/`. The
Makefile's `JAVA17` shell expression has a fallback to `$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home`
that catches this. If you're invoking Spark outside `make`, set
`JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home` manually.

**Spark prints `Total allocation exceeds 95.00% (~1GB) of heap memory` during stage**
Default local-mode driver heap is ~1GB. WWI scale doesn't actually OOM, but the warning is
real. For larger datasets or as a precaution, raise the driver memory in `common/spark.py` or
via `SparkSession.builder.config("spark.driver.memory", "4g")`.

## Platform track (k3d / Argo CD)

**Argo CD UI asks for a login I never set**
Username is `admin`; the password is auto-generated by the Argo CD Helm chart at install and
stored in the `argocd-initial-admin-secret` k8s secret (it is *not* in this repo, by design).
`make argocd-password` prints both. `make argocd-ui` shows them above the port-forward output
— easy to scroll past. Change the password after first login (UI → User Info), after which
the initial secret can be deleted.

**Argo CD app stuck `Unknown` / can't reach the repo**
Argo pulls from the git *remote* in `platform/argocd/api-application.yaml`, not your working
tree — commit + push, and check the repoURL is reachable (public, or add repo credentials in
Argo). `kubectl -n argocd describe application de-playground-api` shows the sync error.

**`Manifest generation error (cached): platform/charts/api: app path does not exist`**
The clone *succeeded* — the path just isn't in the pushed revision. Almost always: the files
are committed locally but not pushed, or (the classic) never committed at all — check with
`git ls-files platform/` and `git log origin/main -1`. Fix with `git add -A && git commit &&
git push`, then hit **Refresh** on the app in the Argo UI: the `(cached)` means Argo cached
the failure and only re-generates on refresh or its ~3-minute poll.

**Pods `ImagePullBackOff` for `de-playground-api:k8s`**
The image is loaded by `make api-image` (`k3d image import`), not pulled from a registry. Re-run
it after rebuilding, and after recreating the cluster (imports don't survive `platform-down`).

## General

When in doubt: `make ps` (what's running), `docker compose logs -f <service>`, and for any
compose edit, `docker compose config` (validates the merged model before you `up`).
