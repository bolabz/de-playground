# Convenience targets. Run `make help` to list them.
# Docker phases mirror the build plan; Python targets use uv.

.DEFAULT_GOAL := help
COMPOSE := docker compose

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
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
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

.PHONY: up-data
up-data:  ## Lean set for the k3d/Airflow track: ONLY SQL Server + SeaweedFS + Elasticsearch
	$(COMPOSE) up -d sqlserver seaweedfs elasticsearch

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

# ---- Gate-0 regression oracle (Python-hardening series, 2026-06) ----
# Capture once on unmodified main (`make baseline`), then `make regression` after each commit
# in the hardening series re-captures into _now/ and diffs against the baseline. Drift => the
# commit changed observable pipeline output. See docs/PYTHON_HARDENING_PLAN.md "Validation".
BASELINE_DIR ?= data/baselines/2026-06-11

# JSON log lines from de_playground.* go to STDERR (the structured logger writes to sys.stderr)
# and include random per-run keys (ts, correlation_id); strip with jq so byte-diffs only flag
# changes in the underlying report data. NOTE: write to a .raw file then jq from the file —
# delta-rs's Rust threadpool keeps the stderr FD open after main() returns, so a `... | jq`
# pipe never sees EOF and hangs on silver/gold inspect.
DE_LOG_STRIP := jq -S 'del(.ts, .correlation_id)'
define _capture_report
	uv run python -m $(1) > $(2).raw 2>&1
	$(DE_LOG_STRIP) $(2).raw > $(2)
	rm -f $(2).raw
endef

.PHONY: baseline
baseline:  ## Capture the Gate-0 regression baseline (run once on unmodified main, post-pipeline)
	@command -v jq >/dev/null || { echo "jq not installed (brew install jq)"; exit 1; }
	@mkdir -p $(BASELINE_DIR)
	$(call _capture_report,de_playground.extract.verify --json,$(BASELINE_DIR)/counts.json)
	$(call _capture_report,de_playground.transform.inspect_lake bronze --json,$(BASELINE_DIR)/inspect_bronze.json)
	$(call _capture_report,de_playground.transform.inspect_lake silver --json,$(BASELINE_DIR)/inspect_silver.json)
	$(call _capture_report,de_playground.transform.inspect_lake gold   --json,$(BASELINE_DIR)/inspect_gold.json)
	curl -fs localhost:9200/fact_sales/_count                                  | jq -S . > $(BASELINE_DIR)/es_count.json
	curl -fs 'localhost:8000/sales/search?q=USB&limit=5'                       | jq -S . > $(BASELINE_DIR)/es_query_usb.json
	curl -fs 'localhost:8000/sales/search?customer_id=1&min_total=100'         | jq -S . > $(BASELINE_DIR)/es_query_customer.json
	curl -fs  localhost:8000/sales/501                                         | jq -S . > $(BASELINE_DIR)/es_query_one.json
	-uv run ruff check .  > $(BASELINE_DIR)/ruff.txt   2>&1
	-uv run mypy src      > $(BASELINE_DIR)/mypy.txt   2>&1
	-uv run pytest -v     > $(BASELINE_DIR)/pytest.txt 2>&1
	@echo ">> baseline captured at $(BASELINE_DIR)"

.PHONY: regression
regression:  ## Re-capture into $(BASELINE_DIR)/_now and diff vs. baseline (exit non-zero on drift)
	@command -v jq >/dev/null || { echo "jq not installed (brew install jq)"; exit 1; }
	@test -d $(BASELINE_DIR) || { echo "no baseline at $(BASELINE_DIR) — run 'make baseline' first"; exit 1; }
	@mkdir -p $(BASELINE_DIR)/_now
	$(call _capture_report,de_playground.extract.verify --json,$(BASELINE_DIR)/_now/counts.json)
	$(call _capture_report,de_playground.transform.inspect_lake bronze --json,$(BASELINE_DIR)/_now/inspect_bronze.json)
	$(call _capture_report,de_playground.transform.inspect_lake silver --json,$(BASELINE_DIR)/_now/inspect_silver.json)
	$(call _capture_report,de_playground.transform.inspect_lake gold   --json,$(BASELINE_DIR)/_now/inspect_gold.json)
	curl -fs localhost:9200/fact_sales/_count                                  | jq -S . > $(BASELINE_DIR)/_now/es_count.json
	curl -fs 'localhost:8000/sales/search?q=USB&limit=5'                       | jq -S . > $(BASELINE_DIR)/_now/es_query_usb.json
	curl -fs 'localhost:8000/sales/search?customer_id=1&min_total=100'         | jq -S . > $(BASELINE_DIR)/_now/es_query_customer.json
	curl -fs  localhost:8000/sales/501                                         | jq -S . > $(BASELINE_DIR)/_now/es_query_one.json
	diff -ru --exclude=_now --exclude='ruff.txt' --exclude='mypy.txt' --exclude='pytest.txt' $(BASELINE_DIR) $(BASELINE_DIR)/_now

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

# ---- Phase 4 orchestration now runs on the cluster: see Phase 5b (Airflow 3 on k3d) below. ----

# ---- Phase 5: platform track (k3d + OpenTofu + Helm + Argo CD + act) ----
# Prereqs (all free/OSS):  brew install k3d kubectl helm opentofu act
K3D_CLUSTER := de-playground
# Phase 5c registry: push from the host via localhost; the chart/kubelet pull via registry.localhost.
# Same store, two names (see platform/k3d-config.yaml).
REGISTRY_PUSH := localhost:5111
API_IMAGE     := de-playground-api
AIRFLOW_IMAGE := de-playground-airflow3

.PHONY: platform-up
platform-up:  ## Phase 5: create the local k3d cluster (1 server + 2 agents; compose unaffected)
	k3d cluster create --config platform/k3d-config.yaml

.PHONY: platform-down
platform-down:  ## Delete the k3d cluster (keeps the compose stack + all data)
	k3d cluster delete $(K3D_CLUSTER)

.PHONY: platform-start
platform-start:  ## Restart the EXISTING k3d cluster after a host/Docker reboot (NOT create)
	k3d cluster start $(K3D_CLUSTER)

.PHONY: platform-stop
platform-stop:  ## Stop the k3d cluster without deleting it (frees RAM; keeps cluster state + the registry)
	k3d cluster stop $(K3D_CLUSTER)

.PHONY: api-push
api-push:  ## Phase 5c: build the API image + push to the k3d registry (tags: git SHA + latest)
	@git diff --quiet && git diff --cached --quiet || { \
		echo "working tree dirty — commit code first (the image is tagged with HEAD's SHA)."; exit 1; }
	@SHA=$$(git rev-parse --short HEAD); \
	echo "building + pushing $(REGISTRY_PUSH)/$(API_IMAGE):$$SHA (+ :latest)"; \
	docker build -t $(REGISTRY_PUSH)/$(API_IMAGE):$$SHA -t $(REGISTRY_PUSH)/$(API_IMAGE):latest ./api; \
	docker push $(REGISTRY_PUSH)/$(API_IMAGE):$$SHA; \
	docker push $(REGISTRY_PUSH)/$(API_IMAGE):latest

.PHONY: api-release
api-release: api-push  ## Phase 5c CD loop: push image, bump the chart tag to the SHA, commit + push (Argo deploys)
	@SHA=$$(git rev-parse --short HEAD); \
	sed -i.bak -E "s|^( *tag: ).*|\1$$SHA # set by 'make api-release' (do not hand-edit)|" platform/charts/api/values.yaml; \
	rm -f platform/charts/api/values.yaml.bak; \
	git add platform/charts/api/values.yaml; \
	git commit -m "deploy(api): $$SHA [skip ci]"; \
	git push; \
	echo "values bumped to $$SHA + pushed -> Argo CD syncs de-playground-api (watch: make argocd-ui)"

.PHONY: registry-ls
registry-ls:  ## List repos + de-playground-api tags in the k3d registry (catalog API)
	@echo "repos:"; curl -s http://$(REGISTRY_PUSH)/v2/_catalog; echo; \
	echo "$(API_IMAGE) tags:"; curl -s http://$(REGISTRY_PUSH)/v2/$(API_IMAGE)/tags/list; echo

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

# ---- Phase 5b: Airflow 3 on the cluster (official chart, KubernetesExecutor) ----
# Image flow is Phase 5c (registry), same as the API. Difference: Airflow is deployed by
# OpenTofu/Helm, not Argo — so its "deploy" is a `tofu apply`, not a git-sync.
.PHONY: airflow3-push
airflow3-push: wheel  ## Phase 5c: build the Airflow 3 image (pipeline baked in) + push to the k3d registry (SHA + latest)
	@git diff --quiet && git diff --cached --quiet || { \
		echo "working tree dirty — commit code first (the image is tagged with HEAD's SHA)."; exit 1; }
	@SHA=$$(git rev-parse --short HEAD); \
	echo "building + pushing $(REGISTRY_PUSH)/$(AIRFLOW_IMAGE):$$SHA (+ :latest)"; \
	docker build -f platform/airflow/Dockerfile -t $(REGISTRY_PUSH)/$(AIRFLOW_IMAGE):$$SHA -t $(REGISTRY_PUSH)/$(AIRFLOW_IMAGE):latest .; \
	docker push $(REGISTRY_PUSH)/$(AIRFLOW_IMAGE):$$SHA; \
	docker push $(REGISTRY_PUSH)/$(AIRFLOW_IMAGE):latest

.PHONY: airflow3-release
airflow3-release: airflow3-push  ## Phase 5c: push image, bump both image tags in airflow-values.yaml, then tofu apply (+ commit)
	@SHA=$$(git rev-parse --short HEAD); \
	sed -i.bak -E "s|^( *tag: ).*|\1$$SHA # set by 'make airflow3-release' (do not hand-edit)|" platform/airflow-values.yaml; \
	rm -f platform/airflow-values.yaml.bak; \
	( cd platform/tofu && tofu apply ) && \
	git add platform/airflow-values.yaml && \
	git commit -m "deploy(airflow): $$SHA [skip ci]" && \
	git push && \
	echo "airflow image $$SHA applied (tofu/helm) + recorded in git"

.PHONY: airflow3-ui
airflow3-ui:  ## Port-forward the Airflow 3 UI to http://localhost:8082 (login admin/admin)
	kubectl -n airflow port-forward svc/airflow-api-server 8082:8080
