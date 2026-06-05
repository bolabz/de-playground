variable "kube_context" {
  description = "kubeconfig context for the local cluster (k3d prefixes cluster names with 'k3d-')"
  type        = string
  default     = "k3d-de-playground"
}

variable "apps_namespace" {
  description = "Namespace the data-platform apps (the API) deploy into"
  type        = string
  default     = "de-playground"
}

variable "argocd_namespace" {
  description = "Namespace for Argo CD"
  type        = string
  default     = "argocd"
}

variable "argocd_chart_version" {
  description = "argo-cd Helm chart version (pin deliberately; verify current with `helm search repo`)"
  type        = string
  default     = "7.7.11"
}

variable "airflow_chart_version" {
  description = "Official apache-airflow/airflow chart version (1.19.x = Airflow 3; keep in step with the image tag in platform/airflow/Dockerfile)"
  type        = string
  default     = "1.19.0"
}
