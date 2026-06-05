# Convenience targets. Run `make help` to list them.
# Docker phases mirror the build plan; Python targets use uv.

.DEFAULT_GOAL := help
COMPOSE := docker compose
AIRFLOW_COMPOSE := docker compose -f airflow/docker-compose.yml

# Spark 3.5 supports Java 8/11/17 only. Pin JDK 17 for the transform targets so they work
# even if your system default `java` is newer (e.g. 26). Tries the macOS java_home registry
# first, then falls back to Homebrew's keg-only openjdk@17 (which java_home won't see).
JAVA17 := $(shell /usr/libexec/java_home -v 17 2>/dev/null || { d="$$(brew --prefix openjdk@17 2>/dev/null)/libexec/openjdk.jdk/Contents/Home"; [ -x "$$d/bin/java" ] && printf '%s' "$$d"; })
.PHONY: require-java17
require-java17:
	@test -n "$(JAVA17)" || { \
		echo "JDK 17 not found (Spark 3.5 needs Java 8/11/17, not newer)."; \
		echo "Install it:  brew install openjdk@17"; exit 1; }

.PHONY: help
help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---- Python env (uv) ----
.PHONY: sync
sync:  ## Install base deps into the venv (uv)
	uv sync

.PHONY: sync-all
sync-all:  ## Install all optional groups (process, serve, eda, dev)
	uv sync --all-extras

.PHONY: lint
lint:  ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: test
test:  ## Run pytest
	uv run pytest

# ---- Docker phases ----
.PHONY: up-ingest
up-ingest:  ## Phase 1: SQL Server + SeaweedFS
	$(COMPOSE) --profile ingest up -d

.PHONY: up-process
up-process:  ## Phase 2: + Spark cluster (2 workers)
	$(COMPOSE) --profile process up -d --scale spark-worker=2

.PHONY: up-serve
up-serve:  ## Phase 3: + Elasticsearch, Kibana, FastAPI
	$(COMPOSE) --profile serve up -d --build --scale spark-worker=2   # --build so api picks up code/Dockerfile changes; --scale preserves worker count

.PHONY: up-all
up-all:  ## Everything (comfortable on 32GB)
	$(COMPOSE) --profile all up -d --scale spark-worker=2

.PHONY: up-observability
up-observability:  ## OTel Collector + Prometheus + Alertmanager + Grafana + exporters (runs alongside)
	$(COMPOSE) --profile observability up -d --build

.PHONY: restore
restore:  ## Restore WideWorldImporters (+DW) into the running SQL Server
	./sql/restore_databases.sh

.PHONY: create-app-login
create-app-login:  ## One-time: create the least-privilege de_extract SQL login the pipeline uses
	./sql/create_app_login.sh

.PHONY: create-buckets
create-buckets:  ## One-time: create the bronze/silver/gold buckets (admin S3 identity)
	uv run python -m de_playground.common.lake

.PHONY: ps
ps:  ## Show running services
	$(COMPOSE) ps

.PHONY: logs
logs:  ## Tail logs (all services)
	$(COMPOSE) logs -f

.PHONY: down
down:  ## Stop services (keep volumes/data)
	$(COMPOSE) --profile all --profile observability --profile submit down --remove-orphans

.PHONY: nuke
nuke:  ## Stop services AND delete volumes (wipes all local data)
	$(COMPOSE) --profile all --profile observability --profile submit down -v --remove-orphans

# ---- Pipeline (implemented in later phases) ----
.PHONY: extract
extract:  ## Phase 1: run the dlt extract (SQL Server -> Bronze)
	uv run python -m de_playground.extract

.PHONY: counts
counts:  ## Count rows in Bronze and compare to the SQL Server source
	uv run python -m de_playground.extract.verify

# ---- CDC (Change Data Capture) path, alongside the watermark extract ----
.PHONY: enable-cdc
enable-cdc:  ## One-time: enable CDC on WWI + the Sales tables (needs SQL Agent)
	./sql/enable_cdc.sh

.PHONY: extract-cdc
extract-cdc:  ## CDC extract: SQL Server change tables -> bronze/wwi_cdc
	uv run python -m de_playground.extract.cdc

.PHONY: silver-cdc
silver-cdc: require-java17  ## Collapse the CDC change feed -> silver/wwi_cdc (deletes applied)
	JAVA_HOME="$(JAVA17)" uv run python -m de_playground.transform silver-cdc

.PHONY: transform
transform: require-java17  ## Phase 2: Bronze -> Silver -> Gold (Delta) via local PySpark
	JAVA_HOME="$(JAVA17)" uv run python -m de_playground.transform

.PHONY: silver
silver: require-java17  ## Phase 2: just the Bronze -> Silver step
	JAVA_HOME="$(JAVA17)" uv run python -m de_playground.transform silver

.PHONY: gold
gold: require-java17  ## Phase 2: just the Silver -> Gold step
	JAVA_HOME="$(JAVA17)" uv run python -m de_playground.transform gold

LAYER ?= gold
.PHONY: inspect
inspect:  ## Inspect a layer (delta-rs/pyarrow, no Spark): make inspect LAYER=bronze|silver|gold
	uv run python -m de_playground.transform.inspect_lake $(LAYER)

# ---- Phase 2 on the CLUSTER (spark-submit) ----
.PHONY: wheel
wheel:  ## Build the de_playground wheel (shipped to executors via --py-files)
	uv build --wheel

.PHONY: cluster-transform
cluster-transform: wheel  ## Submit the transforms to the Spark cluster
	$(COMPOSE) --profile process up -d --scale spark-worker=2   # ensure seaweedfs + master + workers
	$(COMPOSE) --profile process --profile submit run --rm spark-submit

# ---- Phase 3: serving ----
.PHONY: index
index:  ## Phase 3: bulk-index gold/wwi/fact_sales into Elasticsearch
	uv run python -m de_playground.load.to_elasticsearch

.PHONY: kibana-export
kibana-export:  ## Export Kibana saved objects to kibana/saved_objects.ndjson (commit it)
	./kibana/saved_objects.sh export

.PHONY: kibana-import
kibana-import:  ## Re-import kibana/saved_objects.ndjson into Kibana (overwrite)
	./kibana/saved_objects.sh import

# ---- Phase 4: Airflow control plane (separate compose; joins the de network) ----
.PHONY: up-airflow
up-airflow:  ## Phase 4: build + start Airflow (UI :8081). Needs the main stack up first.
	$(AIRFLOW_COMPOSE) up -d --build

.PHONY: down-airflow
down-airflow:  ## Stop Airflow (keeps its metadata volume)
	$(AIRFLOW_COMPOSE) down

.PHONY: airflow-logs
airflow-logs:  ## Tail Airflow logs
	$(AIRFLOW_COMPOSE) logs -f

# ---- Phase 5: platform track (k3d + OpenTofu + Helm + Argo CD + act) ----
# Prereqs (all free/OSS):  brew install k3d kubectl helm opentofu act
K3D_CLUSTER := de-playground

.PHONY: platform-up
platform-up:  ## Phase 5: create the local k3d cluster (1 server + 2 agents; compose unaffected)
	k3d cluster create --config platform/k3d-config.yaml

.PHONY: platform-down
platform-down:  ## Delete the k3d cluster (keeps the compose stack + all data)
	k3d cluster delete $(K3D_CLUSTER)

.PHONY: api-image
api-image:  ## Build the API image and import it into the k3d cluster (no registry yet)
	docker build -t de-playground-api:k8s ./api
	k3d image import de-playground-api:k8s -c $(K3D_CLUSTER)

.PHONY: platform-apply
platform-apply:  ## OpenTofu: provision namespaces + Argo CD into the cluster
	cd platform/tofu && tofu init && tofu apply

.PHONY: api-deploy
api-deploy:  ## Deploy the API chart directly with helm (the pre-GitOps loop)
	helm upgrade --install api platform/charts/api -n de-playground --create-namespace

.PHONY: argocd-app
argocd-app:  ## Register the API as an Argo CD Application (set repoURL in the manifest first)
	kubectl apply -f platform/argocd/api-application.yaml

.PHONY: argocd-password
argocd-password:  ## Print the Argo CD login (user: admin; password generated by the chart at install)
	@echo "================================================="
	@echo "Argo CD login  ->  http://localhost:8443"
	@echo "  username: admin"
	@printf "  password: " && kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo
	@echo "================================================="

.PHONY: argocd-ui
argocd-ui: argocd-password  ## Show the login, then port-forward the UI to http://localhost:8443
	kubectl -n argocd port-forward svc/argocd-server 8443:80

.PHONY: api-forward
api-forward:  ## Port-forward the in-cluster API to http://localhost:8001/docs
	kubectl -n de-playground port-forward svc/api-de-playground-api 8001:80

.PHONY: ci-local
ci-local:  ## Run the GitHub Actions CI workflow locally with act (Apple Silicon needs amd64)
	act push --container-architecture linux/amd64
