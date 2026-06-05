# Phase 5b: Airflow 3 via the OFFICIAL helm chart, KubernetesExecutor, DAGs git-synced from
# the repo. This is how production Airflow actually runs — and it retires the EOL 2.x compose.
# Values live in ../airflow-values.yaml (kept as plain YAML so `helm template` can lint them).

resource "kubernetes_namespace" "airflow" {
  metadata {
    name = "airflow"
    labels = {
      "app.kubernetes.io/managed-by" = "opentofu"
    }
  }
}

resource "helm_release" "airflow" {
  name       = "airflow"
  repository = "https://airflow.apache.org"
  chart      = "airflow"
  version    = var.airflow_chart_version
  namespace  = kubernetes_namespace.airflow.metadata[0].name

  values = [file("${path.module}/../airflow-values.yaml")]

  # First install runs DB migrations and boots several components — don't block the apply on
  # full readiness; watch with `kubectl -n airflow get pods -w` instead.
  wait    = false
  timeout = 900
}
