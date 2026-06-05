# The platform layer, as code: namespaces + Argo CD. The division of labor mirrors the
# real world — IaC (this module) provisions the PLATFORM; Argo CD then deploys the APPS
# from git (see ../argocd/api-application.yaml). Apps are deliberately NOT helm_release'd
# here, so there's exactly one deployer per layer.
#
# Workflow:  make platform-up   (k3d cluster — created by CLI, not tofu: the community k3d
#            provider is unmaintained, and creating the cluster outside tofu keeps the
#            kubeconfig chicken-and-egg out of state)
#            make platform-apply   ->  cd platform/tofu && tofu init && tofu apply

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = var.kube_context
}

provider "helm" {
  kubernetes {
    config_path    = "~/.kube/config"
    config_context = var.kube_context
  }
}

resource "kubernetes_namespace" "apps" {
  metadata {
    name = var.apps_namespace
    labels = {
      "app.kubernetes.io/managed-by" = "opentofu"
    }
  }
}

resource "kubernetes_namespace" "argocd" {
  metadata {
    name = var.argocd_namespace
    labels = {
      "app.kubernetes.io/managed-by" = "opentofu"
    }
  }
}

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = var.argocd_chart_version
  namespace  = kubernetes_namespace.argocd.metadata[0].name

  # Local rig: serve the UI over plain HTTP behind `kubectl port-forward` (no TLS theater).
  set {
    name  = "configs.params.server\\.insecure"
    value = "true"
  }
}
