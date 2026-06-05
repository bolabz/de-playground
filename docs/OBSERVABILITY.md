# Observability — findings & integration plan

How should this pipeline be monitored? Short answer: **Prometheus + Alertmanager is the right
tool for one layer** (service/infrastructure metrics + alerting), but it's not the whole story.
A *data* pipeline needs observability at three levels, and the level that's unique to data
engineering — **data observability** — is the one Prometheus structurally can't give you.

## The model: not 3 pillars, but 3 + 1

Application/infra observability has the classic **three pillars** — **metrics** (numbers over
time: CPU, latency, row counts), **logs** (timestamped events), **traces** (one request/job's
path across services). **OpenTelemetry (OTel)** is the vendor-neutral standard for emitting all
three, and is the convergence point everything is moving toward.

Data engineering adds a fourth lens — **data observability** — with its own five pillars:
**freshness** (did data arrive on time?), **volume** (row counts in range?), **schema** (columns
added/removed/renamed?), **distribution** (values within normal ranges?), and **lineage** (how
does data flow source→consumer?). This is the difference between "the job *ran*" (infra: green
in Prometheus) and "the job produced *correct, fresh* data" (data observability). Both can be
green while the other is on fire — a job can succeed while silently loading zero rows.

## Real-world reference stack (open source, 2026)

The common composable OSS stack, instrumented once via OpenTelemetry:

| Layer | Tool(s) | Role |
|---|---|---|
| Instrumentation | **OpenTelemetry Collector** | one agent collects metrics/logs/traces, exports anywhere |
| Metrics + alerting | **Prometheus + Alertmanager** | scrape metrics, fire alerts (→ Slack/PagerDuty) |
| Logs | **Loki** (or **ELK/Elasticsearch**) | centralized, queryable logs |
| Traces | **Tempo** or **Jaeger** | distributed traces |
| Dashboards | **Grafana** | unify all of the above (the "LGTM" stack = Loki/Grafana/Tempo/Mimir) |
| Lineage | **OpenLineage + Marquez** | what produced what; column-level dependency graph |
| Data quality | **Great Expectations** or **Soda** | rule-based freshness/volume/schema/distribution checks |

Managed/SaaS equivalents you'll meet in industry: **Datadog / Grafana Cloud** (the MELT stack
as a service) and **Monte Carlo / Anomalo / Bigeye** (ML-driven data observability that learns
baselines instead of hand-written rules). The OSS rule-based tools (Great Expectations, Soda)
are the right fit for a code-first team; ML tools catch anomalies you didn't think to assert.

**So, "would we use Prometheus Alertmanager?"** Yes — for service metrics and infra alerting,
it's the standard, and it maps cleanly to Azure (below). But pair it with (a) a logs+traces
path (OTel → Loki/Tempo or reuse Elasticsearch), and (b) a **data**-observability layer
(quality checks + lineage), which is the genuinely DE-specific part.

## How it maps onto THIS PoC, component by component

Each component already emits telemetry; observability is mostly *collecting* it.

| Component | Emits | How to collect here |
|---|---|---|
| **Airflow** (control) | task metrics (durations, success/fail, scheduler heartbeat), task logs, SLAs | StatsD→`statsd-exporter`→Prometheus (classic) **or** native **OpenTelemetry** (Airflow 2.7+ metrics; 3.2 adds custom-span traces). Task-failure **callbacks** → Alertmanager/Slack. StatsD is being deprecated for OTel. |
| **dlt** (extract) | a run **trace** with extract/normalize/load timings + per-table **row counts**; can emit to Sentry | already printed via `last_normalize_info`; persist the trace to a Bronze `_dlt_trace` table for freshness/volume monitoring (cheap, high value) |
| **Spark** (transform) | executor/stage/shuffle metrics; event logs | **PrometheusServlet** sink (Spark 3.0+) exposes metrics in Prometheus format; History Server replays completed-app UIs from event logs |
| **SQL Server** | DB/query metrics | `sql_exporter` → Prometheus |
| **SeaweedFS** | S3/volume metrics | built-in Prometheus metrics endpoint |
| **Elasticsearch** | cluster/index metrics | `elasticsearch_exporter`; **and you already run ES/Kibana** — reuse it as the **logs backend** instead of standing up Loki |
| **FastAPI** (serving) | request latency/throughput/errors | `prometheus-fastapi-instrumentator` or OTel auto-instrumentation |
| **Containers/host** | CPU/mem/disk per container | `cAdvisor` + `node-exporter` → Prometheus |
| **Data quality** | freshness/volume/schema/distribution | **Great Expectations**/**Soda** suite run as an Airflow task between layers (fail the DAG on violation) |
| **Lineage** | run→input→output graph | **OpenLineage** emitters in Airflow + Spark → **Marquez** UI |

A nice property of this rig: **Elasticsearch + Kibana are already here**, so the logs pillar is
"free" — point an OTel collector / Filebeat at the container logs and index them, and Kibana
becomes your log explorer (the same way it's your Power-BI stand-in for Gold data).

## Azure mapping (so the concepts transfer)

| Local (OSS) | Azure |
|---|---|
| OpenTelemetry Collector | Azure Monitor OpenTelemetry / Application Insights SDK |
| Prometheus | **Azure Monitor managed Prometheus** |
| Alertmanager | **Azure Monitor Alerts** (action groups → email/Teams/PagerDuty) |
| Grafana | **Azure Managed Grafana** |
| Loki / ELK (logs) | **Log Analytics** (KQL) |
| Tempo / Jaeger (traces) | **Application Insights** (distributed tracing) |
| OpenLineage + Marquez | **Microsoft Purview** (lineage + governance) |
| Great Expectations / Soda | Purview Data Quality / Fabric data-quality rules / GE on Databricks |
| (pipeline run history) | ADF / Fabric built-in monitoring + Azure Monitor |

Azure Monitor is the umbrella (metrics store + Log Analytics + Application Insights + Alerts).
The OSS stack maps almost 1:1 because Azure now offers *managed Prometheus and Grafana* — so the
instrumentation and dashboards you'd build here largely lift-and-shift.

## Recommended integration for this PoC (phased, proportionate)

Don't boil the ocean on a laptop. Three tiers, cheapest-highest-value first:

**Tier 1 — pipeline signal, almost no new infra.** Persist the dlt run trace (row counts +
timings) to a Bronze `_dlt_trace` table; add Airflow `on_failure_callback` alerting; ship
container logs into the Elasticsearch you already run and explore them in Kibana. This already
answers "did it run, how long, how many rows, what broke" — the 80% for a solo rig.

**Tier 2 — metrics + dashboards.** Add an `observability` compose profile: OpenTelemetry
Collector + Prometheus + Alertmanager + Grafana, plus `cAdvisor`/`node-exporter` and the
SeaweedFS/ES/SQL exporters; turn on Airflow's OTel metrics and Spark's PrometheusServlet sink;
add `prometheus-fastapi-instrumentator` to the API. Now you have service health + alert rules,
and the Spark-UI shuffle story shows up in Grafana too.

**Tier 3 — data observability (the DE-specific layer; overlaps the backlog).** Add a Great
Expectations or Soda suite as an Airflow task between Bronze→Silver→Gold (fail the run on a
freshness/volume/schema/distribution breach — this is the "data-quality gate" already on the
backlog). Add OpenLineage emitters in Airflow + Spark → Marquez for a lineage graph (the local
stand-in for Purview).

The honest framing for the rig: Tiers 1 and 3 teach the *data-engineering-specific* lessons
(pipeline + data observability) and are worth doing; Tier 2 (Prometheus/Grafana/OTel) teaches
the *general* observability mechanics that transfer to any system and map directly to Azure
Managed Prometheus/Grafana — valuable, but heavier, and partly theatre on one machine (you're
watching one box's metrics).

## Implemented in this rig (Tier 2 + ELK logs + OpenTelemetry)

The `observability` compose profile (`make up-observability`) and `observability/` configs
implement the metrics/logs path, unified via OpenTelemetry:

- **OpenTelemetry Collector** (`otel-collector-config.yaml`) — tails Docker container logs →
  Elasticsearch (`otel-logs`, the ELK "L", browse in Kibana); receives OTLP from apps; exposes
  metrics for Prometheus; traces → debug (add Jaeger/Tempo to persist).
- **Prometheus + Alertmanager + Grafana** — scrape exporters (cAdvisor, node-exporter,
  elasticsearch-exporter, SeaweedFS `-metricsPort`, Spark PrometheusServlet); example alert
  rules (`rules.yml`); Grafana auto-provisioned with Prometheus + Elasticsearch-logs datasources.
- **FastAPI is OTel-instrumented** (`opentelemetry-instrument` in `api/Dockerfile`) → OTLP to the
  collector — the live end-to-end OpenTelemetry example.
- **Spark** ships a `metrics.properties` PrometheusServlet sink; **Airflow** OTel metrics would
  be enabled via the `config.metrics`/`config.traces` keys in `platform/airflow-values.yaml`
  (Airflow 3 on the cluster) — tracked in BACKLOG P3.
- **Structured logging in the pipeline** (2026-06-03): `src/de_playground/common/logging.py`
  emits JSON in non-TTY contexts and pretty single-line text in TTY, with a per-run
  `correlation_id` (contextvar) attached to every line so extract → transform → index entries
  for the same run can be grouped after the fact. The OTel Collector picks these up via the
  Docker logging driver and ships them to `otel-logs` in Elasticsearch — query in Kibana with
  `correlation_id : "abc123…"` to reconstruct a single run.

Not yet wired (deliberate): a traces backend (Jaeger/Tempo) and Tier-3 data observability
(Great Expectations/Soda quality gate + OpenLineage/Marquez lineage) — tracked in
[`BACKLOG.md`](BACKLOG.md). Verified by config/syntax + the FastAPI instrumentation; the
live stack (Docker-Desktop log-tailing and the cAdvisor/node-exporter VM caveats) is validated
on-machine.

## Sources

- [Three pillars + data observability (DataGalaxy)](https://www.datagalaxy.com/en/blog/3-pillars-of-data-observability/) · [pipeline observability (datalakehousehub)](https://datalakehousehub.com/blog/2026-02-de-best-practices-09-observability-monitoring/)
- [OpenTelemetry](https://opentelemetry.io/docs/what-is-opentelemetry/)
- [Airflow metrics + OTel](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/logging-monitoring/metrics.html) · [AIP-49 OpenTelemetry for Airflow](https://cwiki.apache.org/confluence/display/AIRFLOW/AIP-49+OpenTelemetry+Support+for+Apache+Airflow)
- [Spark monitoring / PrometheusServlet](https://spark.apache.org/docs/latest/monitoring.html)
- [dlt monitoring + trace](https://dlthub.com/docs/running-in-production/monitoring)
- [OpenLineage](https://openlineage.io/docs/) · [Marquez](https://marquezproject.ai/)
- [Monte Carlo vs Great Expectations vs Soda (2026)](https://www.modern-datatools.com/compare/monte-carlo-vs-great-expectations-vs-soda) · [OSS data-quality landscape 2026 (DataKitchen)](https://datakitchen.io/blog/the-2026-open-source-data-quality-and-data-observability-landscape/)
- [LGTM stack / Grafana vs Azure Monitor](https://cubeapm.com/blog/azure-monitor-vs-grafana-vs-cubeapm/) · [Grafana LGTM](https://community.grafana.com/t/building-unified-observability-with-the-lgtm-stack/157752)
