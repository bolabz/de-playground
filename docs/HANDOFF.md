# Handoff & production-readiness snapshot

A **snapshot** comparing this rig against modern data-engineering industry standards.
Forward work and EOL upgrade plans live in [`BACKLOG.md`](BACKLOG.md); refactor / decision
history lives in [`../CHANGELOG.md`](../CHANGELOG.md); design constraints by intent live in
[`ARCHITECTURE.md`](ARCHITECTURE.md) ("Deliberate non-goals"). This doc's unique value is the
**snapshot table** (where we stand vs. the modern stack) and the **industry context** at the
bottom.

> **Refreshed 2026-06-03.** Snapshot reflects current state. Two pinned components are
> **past EOL** (Spark 3.5, Airflow 2.11) — see [BACKLOG P1](BACKLOG.md#p1--version-upgrades-past-eol-as-of-2026-06-03)
> for the upgrade plan.

## TL;DR

This rig is **exemplary as a learning/reference PoC** and follows modern Python + data-eng
hygiene well. The remaining productionization gaps are tracked in
[BACKLOG P2](BACKLOG.md#p2--productionization-from-docshandoffmd): managed cloud target +
IaC, data quality / contracts, lineage, secrets vault. The urgent firefighting is the EOL
version upgrades ([BACKLOG P1](BACKLOG.md#p1--version-upgrades-past-eol-as-of-2026-06-03)).
These are exactly the "~20% that doesn't transfer" the architecture doc called out — none
are surprises.

## Where we're exemplary vs. where we deviate

| Area | Status | Notes |
|---|---|---|
| Python project shape | ✅ exemplary | src layout, `pyproject.toml` as single source, `uv` + committed `uv.lock`, `ruff` + `mypy`, type hints everywhere, thin runners + pure functions |
| Data-eng patterns | ✅ exemplary | medallion, idempotency, high-watermark + CDC, ACID Delta, denormalized serving, thin DAG |
| Security (local) | ✅ good | least-privilege SQL login + non-admin S3 identity, `.env` gitignored |
| Observability | ✅ good | OpenTelemetry + Prometheus/Grafana/Alertmanager + ELK logs (Tier 2) |
| Docs | ✅ strong | ARCHITECTURE / GLOSSARY / CONTRIBUTING / OBSERVABILITY / TROUBLESHOOTING (stable) + BACKLOG / HANDOFF / CHANGELOG (dated) |
| Structured logging | ✅ done | `src/de_playground/common/logging.py` — JSON + pretty + correlation_id (landed 2026-06-03) |
| CI/CD | ✅ done | `.github/workflows/ci.yml` gates `ruff check` + `ruff format --check` + `mypy src` + `pytest` on every push/PR |
| Pre-commit | ✅ done | `.pre-commit-config.yaml` with ruff + standard hooks; install via `uv run pre-commit install` |
| LICENSE | ✅ done | MIT license at repo root |
| CHANGELOG | ✅ done | `CHANGELOG.md` (Keep a Changelog format) with dated decision entries |
| Dev Container | ✅ done | `.devcontainer/devcontainer.json` (MCR Python 3.11 + Java 17 + docker-outside-of-docker) |
| Troubleshooting runbook | ✅ done | `docs/TROUBLESHOOTING.md` (symptom → cause → fix) |
| Compose modularity | ✅ done | root `docker-compose.yml` uses `include:` for `compose/{core,spark,serving,observability}.yml` |
| **Automated tests in CI** | ⚠️ gap | transform logic verified ad hoc in Spark, not in the suite (4/15 modules covered) |
| **Data quality / contracts** | ❌ missing | no Great Expectations/Soda gate, no freshness SLA |
| **IaC / deploy target** | ❌ missing | docker-compose ≠ production; no Terraform/Bicep, no K8s/cloud target |
| **Secrets** | ⚠️ by design | static `.env`, not a vault (the Azure-only lesson) |
| **Lineage** | ❌ missing | no OpenLineage/Marquez |
| **ADRs** | ⚠️ proto | decision rationale lives in `CHANGELOG.md` + `ARCHITECTURE.md` non-goals; no `docs/adr/` yet |
| **Versions** | 🔥 PAST EOL | Spark 3.5 (52d past), Airflow 2.11 (42d past), ES 8.14 — upgrade is urgent |

## Remaining work

- **Urgent firefighting:** [BACKLOG P1](BACKLOG.md#p1--version-upgrades-past-eol-as-of-2026-06-03) — Spark 4, Airflow 3, ES 8.19+ upgrades (both Spark and Airflow EOL'd more than a month ago).
- **Productionization queue:** [BACKLOG P2](BACKLOG.md#p2--productionization-from-docshandoffmd) — data contracts, lineage, secrets vault, IaC, ADRs, Spark unit tests, compose healthchecks, `make check-env`.
- **Observability tier-3:** [BACKLOG P3](BACKLOG.md#p3--observability-follow-ups-from-docsobservabilitymd) — traces backend, dlt run-trace persistence, Airflow OTel.

## How other teams handle this (real-world)

The mainstream OSS-friendly shape in 2026: **uv + ruff + mypy/ty** for Python; **pre-commit +
GitHub Actions** gating lint/type/test; **Dev Containers / Codespaces** for environment parity;
**ADRs + Keep-a-Changelog** for decisions/history; **OpenTelemetry → Prometheus/Grafana/Loki**
for ops observability and **Great Expectations/Soda + OpenLineage** for *data* observability;
**Terraform** for IaC; and a managed orchestrator + lakehouse (Airflow 3 / Astronomer, or ADF +
Fabric/Databricks) rather than self-hosted compose. We now match most of that list (uv/ruff/mypy,
pre-commit, GH Actions, Dev Container, Keep-a-Changelog, OTel→Prom/Grafana/ELK, structured
logging); the remaining gaps are **ADRs, data contracts, lineage (OpenLineage), IaC, and a
managed cloud target.**

## Sources

- [DE best-practices / production checklist (dev.to)](https://dev.to/alexmercedcoder/data-engineering-best-practices-the-complete-checklist-21e9) · [CI/CD for data pipelines (Gable)](https://www.gable.ai/blog/ci-cd-for-data-pipelines) · [testing data pipelines (Atlan)](https://atlan.com/testing-data-pipelines/)
- [Python project setup 2026: uv + ruff (KDnuggets)](https://www.kdnuggets.com/python-project-setup-2026-uv-ruff-ty-polars) · [Scientific-Python task runners](https://learn.scientific-python.org/development/guides/tasks/) · [poethepoet](https://github.com/nat-n/poethepoet)
- [Docker Compose `include`](https://docs.docker.com/compose/how-tos/multiple-compose-files/include/) · [Compose modularity with include (Docker blog)](https://www.docker.com/blog/improve-docker-compose-modularity-with-include/)
- [ADRs (adr.github.io)](https://adr.github.io/) · [MADR](https://github.com/adr/madr) · [ADR (Martin Fowler)](https://martinfowler.com/bliki/ArchitectureDecisionRecord.html)
- [Dev Containers spec](https://github.com/devcontainers/spec) · [Dev Containers 2026](https://viprasol.com/blog/devcontainers/)
- EOL: [Spark versioning policy](https://spark.apache.org/versioning-policy.html) · [Spark EOL](https://eosl.date/eol/product/apache-spark/) · [Airflow supported versions](https://airflow.apache.org/docs/apache-airflow/stable/installation/supported-versions.html) · [PostgreSQL versioning](https://www.postgresql.org/support/versioning/) · [Elasticsearch EOL](https://endoflife.date/elasticsearch)
