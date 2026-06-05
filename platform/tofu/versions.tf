# OpenTofu root module for the local platform (works with `tofu`; Terraform-compatible HCL).
# OpenTofu chosen over Terraform for the project's free/OSS constraint (Terraform is BUSL
# since 2023; OpenTofu is the MPL-2.0 Linux Foundation fork with the same provider model).
terraform {
  required_version = ">= 1.6"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17" # v2 syntax (kubernetes block + set blocks); v3 changed the schema
    }
  }
}
