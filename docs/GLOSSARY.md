# Glossary

Terminology used across this project. Grouped by theme. Acronyms are expanded on first use.

## Architecture & patterns

- **ETL** (Extract, Transform, Load) — transform data *before* loading it into the destination. The legacy pattern, used when storage was expensive.
- **ELT** (Extract, Load, Transform) — load raw data first, transform it *inside* the warehouse/lake afterward. The modern default with cheap cloud compute.
- **OLTP** (Online Transaction Processing) — row-oriented databases optimized for many small reads/writes (e.g., an app's SQL Server). The system of record.
- **OLAP** (Online Analytical Processing) — columnar storage optimized for large aggregate reads (warehouses, lakes).
- **Medallion architecture** — layering data as **Bronze** (raw), **Silver** (cleaned/conformed), **Gold** (curated, business-ready). Maps to raw → cleaned → API-ready.
- **Data lake** — cheap object storage holding raw + processed files (often Parquet). Schema-on-read.
- **Data warehouse** — structured, query-optimized analytical store. Schema-on-write.
- **Lakehouse** — a lake plus warehouse-like features (ACID, schema, time-travel) via table formats like Delta/Iceberg.
- **DAG** (Directed Acyclic Graph) — a dependency graph of tasks with no cycles. How orchestrators model "what runs after what."
- **Idempotency** — re-running an operation produces the same result without duplicating or corrupting data. Core reliability property.
- **High-watermark / incremental load** — tracking the latest processed value (e.g., max timestamp) so each run pulls only new/changed rows.
- **Backfill** — reprocessing historical data, e.g., recomputing last quarter after a logic fix.
- **CDC** (Change Data Capture) — capturing row-level changes (insert/update/delete) from a source DB as they happen. In SQL Server, an async job reads the transaction log into `cdc.*_CT` change tables with before/after images (needs SQL Server Agent). This rig uses CDC (`extract/cdc.py`).
- **Change Tracking (CT)** — SQL Server's lighter sibling to CDC: records *which* rows changed + the operation + a bigint version, but not the old/new values (you join back to the table). No Agent required. We chose CDC for the richer feed; CT is the simpler alternative if you don't need history.
- **Schema-on-read** — structure is applied when data is queried (lakes). **Schema-on-write** — structure enforced at write time (warehouses).
- **Partitioning** — splitting data by a key (e.g., date) so engines read/process only what's needed, in parallel.
- **Shuffle** — redistributing data across nodes during a distributed job (e.g., for a join/group-by). The expensive step in Spark.
- **Denormalization** — duplicating/flattening data for fast reads in a serving store, trading write efficiency for read speed.
- **Lazy evaluation** — declaring a query/plan that the engine optimizes before executing (Spark, Polars, dbt, Airflow all do this).
- **Reverse ETL** — pushing curated warehouse data back into operational tools (CRM, ads). Also called activation.
- **Control / batch / serving planes** — the three runtime roles: orchestration, scheduled data jobs, and always-on request handling.

## Storage & formats

- **Parquet** — columnar file format; the default for analytical data on lakes.
- **Delta Lake** — open table format (Parquet + transaction log) adding ACID, versioning, and time-travel. Native to Databricks/OneLake.
- **Apache Iceberg** — alternative open table format with similar guarantees; the broadly adopted open standard.
- **ACID** (Atomicity, Consistency, Isolation, Durability) — transactional guarantees that make concurrent writes and reprocessing safe.
- **Apache Arrow** — in-memory columnar format enabling zero-copy data handoff between pandas, Polars, Spark, DuckDB.
- **Object storage** — store/retrieve data as objects in buckets via an HTTP API (S3-style). The lake's foundation.
- **S3 / S3A** — Amazon's de-facto object storage API; **S3A** is the Hadoop/Spark client used to read/write S3-compatible stores.
- **Inverted index** — maps terms → documents containing them; the structure behind fast full-text search (Elasticsearch).

## Tools in this stack

- **SQL Server** — Microsoft's relational DB (the OLTP source). Developer Edition is free for dev/test (proprietary). ↔ Azure SQL Database.
- **WWI** (WideWorldImporters) — Microsoft's sample database used as the source dataset.
- **SeaweedFS** — Apache 2.0, actively maintained S3-compatible object store. Local stand-in for the data lake. ↔ ADLS Gen2.
- **Spark / PySpark** — distributed data processing engine; PySpark is its Python API. ↔ Azure Databricks / Synapse / Fabric Spark.
- **dlt** (data load tool) — Python-first, Apache 2.0 ingestion library with incremental loading. ↔ ADF Copy Activity.
- **pandas** — single-machine DataFrame library; used at the edges (EDA, small last-mile results), never the heavy path.
- **Polars** — fast, multi-threaded DataFrame library with lazy execution; modern alternative to pandas for single-machine pipelines.
- **delta-rs / `deltalake`** — Python library to read/write Delta tables without a JVM.
- **Airflow** — workflow orchestrator; schedules DAGs with retries and backfills. ↔ ADF pipelines/triggers.
- **Elasticsearch** — distributed search/analytics engine over an inverted index. ↔ Azure AI Search.
- **Kibana** — visualization/dashboard UI for Elasticsearch. ↔ Power BI.
- **FastAPI** — Python web framework for building APIs; the serving-plane layer over the data stores.
- **uvicorn** — ASGI server that runs FastAPI apps.
- **Docker / Docker Compose** — containerization and multi-service local orchestration. Engine is free; Desktop is free for personal use.

## Azure services

- **ADF** (Azure Data Factory) — managed ingestion (Copy Activity) + orchestration (pipelines/triggers). Spans the control + batch planes.
- **ADLS Gen2** (Azure Data Lake Storage Gen2) — object storage with hierarchical namespace; the Azure data lake.
- **OneLake** — Microsoft Fabric's unified SaaS data lake, built on ADLS Gen2. "OneDrive for data."
- **Azure Databricks** — managed Spark + Delta Lakehouse platform on Azure.
- **Azure Synapse Analytics** — integrated SQL + Spark analytics platform (predecessor pattern to Fabric).
- **Microsoft Fabric** — unified SaaS analytics platform consolidating Data Factory, Synapse, Power BI, and OneLake; the increasingly default new-build choice.
- **Azure SQL Database / SQL MI** (Managed Instance) — managed relational DB; cloud equivalent of SQL Server.
- **Azure AI Search** (formerly Cognitive Search) — managed search service; cloud equivalent of Elasticsearch.
- **Power BI** — Microsoft's BI/dashboard tool.
- **Entra ID** (formerly Azure Active Directory) — identity and access management.
- **Azure Key Vault** — managed secrets/keys/certificates store.
- **Microsoft Purview** — data governance, classification, and lineage.
- **API Management** — gateway for publishing/securing/throttling APIs.
- **Azure Container Apps / App Service** — managed compute for hosting containerized apps like FastAPI.
- **Azure ML** (Machine Learning) — managed platform for training/serving models (the PyTorch target).

## Python & packaging

- **`pyproject.toml`** — the modern standard file declaring project metadata and dependencies.
- **uv** — fast Rust-based Python package/environment manager (replaces pip + virtualenv + pyenv).
- **Lockfile (`uv.lock`)** — pins exact dependency versions for reproducible installs.
- **Virtual environment** — an isolated per-project set of installed packages.
- **Wheel** — a built, installable Python package distribution format.
- **Type hints** — optional annotations (`x: int`); not enforced at runtime unless checked by tools.
- **mypy** — static type checker for Python (the TypeScript-style guardrail).
- **ruff** — fast Rust-based linter + formatter (replaces flake8 + black + isort).
- **pytest** — the standard Python testing framework.
- **pydantic-settings** — typed configuration loaded from environment variables (12-factor config).
- **ASGI** (Asynchronous Server Gateway Interface) — the async server interface FastAPI targets.
