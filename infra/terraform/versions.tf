# CHIMERA Checkout Shield - Terraform / provider version pins.
# SANDBOX ONLY. UNTESTED: this configuration has NEVER been applied.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # No remote backend is configured. State is LOCAL by default and may contain
  # sensitive values. For shared use, configure an encrypted remote backend
  # (e.g. S3 + DynamoDB locking) before running anything. See README.md.
  # backend "s3" {}
}