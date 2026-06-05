output "next_steps" {
  description = "What to do after apply"
  value       = <<-EOT
    Argo CD installed in namespace '${var.argocd_namespace}'.
      UI + admin password:   make argocd-ui   (then open http://localhost:8443, user: admin)
      Register the API app:  set repoURL in platform/argocd/api-application.yaml, then
                             make argocd-app
      Pre-GitOps fallback:   make api-deploy  (helm installs the chart directly)
  EOT
}
