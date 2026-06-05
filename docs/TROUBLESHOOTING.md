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

**`unable to prepare context: path ".../compose/..." not found`**
Compose resolves relative build paths against the compose file's directory. The `compose/*.yml`
files use `../` for repo-root paths and `build: ../<dir>` accordingly. Validate any compose
change with `docker compose config` before `up`. (Airflow now runs on the cluster, not compose —
for DAGs not showing in the Airflow 3 UI, see the git-sync entry under *Platform track*.)

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

**Pods `ImagePullBackOff` / `ErrImagePull`**
- **API** (`k3d-registry.localhost:5111/de-playground-api:<sha>`, Phase 5c) — the image isn't in
  the registry, or the registry is empty after a cluster *recreate*. Re-run `make api-release` (or
  `make api-push`), then `make registry-ls` to confirm the tag is there. The chart's image `tag`
  in `platform/charts/api/values.yaml` must be a tag that exists in the registry. NB: the chart
  ref uses `k3d-registry.localhost:5111` (the kubelet's name); you *push* to `localhost:5111` —
  same store, don't "fix" the chart to `localhost` (the node can't reach its own localhost).
- **Airflow** (`de-playground-airflow3:k8s`) — still side-loaded via `make airflow3-image`
  (`k3d image import`); re-run it after a rebuild or a cluster recreate (imports don't survive
  `platform-down`).

**`docker push` to the registry fails (`connection refused` / `port 5000 already in use`)**
The registry binds host port **5111**, not 5000 (macOS Control Center/AirPlay holds 5000 — that's
why we avoided it). Confirm the registry container is up: `docker ps -f name=k3d-registry.localhost`.
After a Docker restart the registry comes back with `make platform-start`; if not, `docker start
k3d-registry.localhost`. Sanity-check the API works: `curl http://localhost:5111/v2/_catalog`.

**Airflow 3 task pods crash with `No such file or directory: /opt/pipeline-venv/...`**
Task pods are running the stock Airflow image instead of ours — `images.pod_template` in
`platform/airflow-values.yaml` must point at `de-playground-airflow3:k8s` (it does NOT inherit
`images.airflow`; KubernetesExecutor task pods have their own image knob).

**Airflow 3 on k3d: DAG missing / stale in the UI**
DAGs git-sync from the *remote*'s `dags/` folder every 60s — commit + push DAG changes (the
working tree is invisible to the cluster). Code changes under `src/` are different: they're
baked into the image, so `make airflow3-image` and re-trigger.

**`make platform-apply` returns before Airflow is up / first boot looks stuck**
The release applies with `wait=false`; first boot runs DB-migration + user-creation jobs before
the api-server/scheduler/dag-processor settle. Watch `kubectl -n airflow get pods -w` — a few
minutes on first install is normal.

**Task logs show "Network Error" / "Could not read served logs ... NameResolutionError"**
Expected with KubernetesExecutor: the task pod is deleted when it finishes, so the UI can't
stream live logs from a pod that no longer exists. Two fixes are wired in: **remote logging to
SeaweedFS** (`config.logging` in `platform/airflow-values.yaml` → logs persist to
`s3://bronze/airflow-logs` and become readable in the UI after the pod dies — needs the amazon
provider in the image and a rebuilt image). For a *running* pod right now, bypass the UI:
`kubectl -n airflow logs -f <task-pod>`.

**Tasks fail then retry; `airflow-api-server` shows `OOMKilled` (repeatedly)**
Memory pressure on the shared machine — in Airflow 3, task pods report state to the api-server,
so if it's OOM-killed mid-task the task is marked failed and retried even though the work ran
(you'll see a `0/1 Completed` task pod — exit 0 — paired with a failed task). Repeated
api-server restarts = the *host* is out of RAM, not just the pod. Fix in order of impact:
1. **Free the host:** the k3d/Airflow track does NOT need the full compose stack. Run the lean
   set — `make down && make up-data` (SQL Server + SeaweedFS + ES only).
   The transform task runs Spark *inside its own pod*, so the compose Spark cluster, Kibana,
   compose-API, and observability are all dead weight here.
2. We also bumped `apiServer.resources` (512Mi req / 1Gi limit) — apply via `tofu apply`.
Read a *failed/kept* task pod's logs directly (failed pods aren't deleted):
`kubectl -n airflow logs <task-pod>`.

**`transform_silver_gold` task pod shows `OOMKilled` (while extract `Completed`)**
Different from the api-server OOM above — here the *task pod itself* is killed, fast (~30s =
JVM start + first Spark action). The transform runs PySpark in **local mode inside the pod**;
with no memory limit the driver JVM sizes `-Xmx` to ~¼ of the whole node, and on the shared
Docker Desktop VM (the compose data stack + the k3d cluster live in the *same* VM) that tips it
into kernel OOM. Airflow then logs `reported ... finished with state failed, but the task
instance's state attribute is running ... Pod failed because of None` — that's the executor
reconciling a pod that vanished mid-run, a *symptom*, not a second bug. Two-part fix (both in
`platform/airflow-values.yaml`, apply with `tofu apply` — no image rebuild):
1. `SPARK_DRIVER_MEMORY: "2g"` in the `env` list — caps the driver heap. In local/client mode
   the JVM is already up when the builder runs, so `spark.driver.memory` is ignored;
   `SPARK_DRIVER_MEMORY` is read by spark-submit at launch.
2. `workers.resources` (request 2Gi / limit 3.5Gi, cpu limit `2`) — gives the KubernetesExecutor
   task pod an explicit budget the scheduler reserves, and the cpu limit makes cgroup-aware
   JDK17 expose ~2 cores so `local[*]` spawns fewer threads (less concurrent memory).
The budget must fit the VM: ensure Docker Desktop RAM ≥ ~12–16Gi (Settings → Resources) on top
of emulated SQL Server + ES. If the pod sits `Pending` instead, the node can't satisfy the
request → raise the VM or lower the request.

**Task pods fail with `Failed to resolve 'host.k3d.internal'` (NameResolutionError)**
The host bridge isn't resolving inside task pods, so they can't reach the compose data services
(lake/SQL/ES). This is the *real* cause of extract failures (distinct from the api-server OOM).
Diagnose: `kubectl run -it --rm dns --image=busybox:1.36 --restart=Never -- sh -c "nslookup
host.k3d.internal; nslookup host.docker.internal"`.
- If `host.docker.internal` resolves but `host.k3d.internal` doesn't → set all data endpoints in
  `platform/airflow-values.yaml` (the `env` list + the `aws_s3` conn) to `host.docker.internal`,
  then `tofu apply`.
- If neither resolves → k3d didn't inject the host record. `brew upgrade k3d`, recreate the
  cluster (`make platform-down && make platform-up`), then `make api-release`/`make airflow3-image`
  + `make platform-apply` (the registry, imports, and releases don't survive a cluster recreate).
Whichever name you use, the SeaweedFS/SQL/ES **services must be up** (`make up-data`) — a DNS
*resolution* failure (`getaddrinfo`) means the name; a *connection refused* means the service.

**Stale `kubectl port-forward` after a deploy ("can't reach :8082/:8443/:8001")**
`tofu apply`/`helm upgrade` replaces pods, which kills any port-forward bound to the old pod.
Just re-run the forward target (`make airflow3-ui` / `make argocd-ui` / `make api-forward`).

**Remote-logging S3 errors (`NoSuchBucket` / `SignatureDoesNotMatch` / connection refused)**
The `aws_s3` connection (`AIRFLOW_CONN_AWS_S3` in values) must reach SeaweedFS: `bronze` bucket
exists (`make create-buckets`), `host.docker.internal:8333` is resolvable from pods, and the creds
match your `.env` app identity. SeaweedFS needs path-style addressing (already set in the conn's
`config_kwargs`).

## General

When in doubt: `make ps` (what's running), `docker compose logs -f <service>`, and for any
compose edit, `docker compose config` (validates the merged model before you `up`).
