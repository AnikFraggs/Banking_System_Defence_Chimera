# CHIMERA Checkout Shield - AWS Terraform scaffold

**Status: DEFERRED — UNTESTED. NEVER APPLIED.** This scaffold is intentionally
parked: it **will be upgraded later, during the deployment phase**, once the
local sandbox stack and its measured benchmarks are signed off. Until then it
is a reference starting point only, not part of the running system. It has
**never been run** against an AWS account, and `terraform apply`
**creates billable resources**: an EKS control plane, EC2 worker nodes, a NAT
gateway + Elastic IP, an RDS PostgreSQL instance, an ElastiCache Redis
replication group, and an S3 bucket. Review cost and security before applying.

**SANDBOX ONLY.** Defensive payment reference app. Never use real cards, real
cardholder data, or real PayPal accounts. The default `environment` is `sandbox`.

## What it provisions

- **VPC** with public + private subnets across `az_count` AZs, an Internet
  Gateway, a single NAT gateway, and route tables.
- **EKS** cluster (`aws_eks_cluster`) with a **managed node group**
  (`aws_eks_node_group`) in the private subnets, plus the required IAM roles.
- **RDS PostgreSQL** (`aws_db_instance`, engine `postgres`, demo `db.t3.micro`).
  The master password is **managed by RDS in Secrets Manager**
  (`manage_master_user_password = true`) so no password is stored in Terraform.
- **ElastiCache Redis** replication group (`cache.t3.micro`, 2 nodes, automatic
  failover, encryption at rest + in transit).
- **S3** artifact bucket: private (public access blocked), versioned, AES256
  encrypted.

## Credentials (no hardcoded secrets)

AWS credentials are resolved through the **standard provider chain**:
environment variables (`AWS_ACCESS_KEY_ID`, ...), the shared
`~/.aws/credentials` / `~/.aws/config` files, or an attached IAM role. There are
**no access key / secret key variables** in this configuration. Optionally set
`aws_profile` to select a named profile:

```
terraform init
terraform plan  -var="region=us-west-2" -var="aws_profile=my-sandbox-profile"
```

Do **not** commit credentials, `terraform.tfstate`, or `*.tfvars` containing
secrets. State is **local** by default and can contain sensitive values;
configure an encrypted remote backend (e.g. S3 + DynamoDB locking) for shared
use before running anything.

## Files

| File | Purpose |
| --- | --- |
| `versions.tf` | Terraform + AWS provider version pins; backend placeholder |
| `variables.tf` | Region, sizing, naming, tags. No secrets. |
| `main.tf` | VPC, EKS + node group, RDS, ElastiCache, S3 |
| `outputs.tf` | Ids/endpoints (not secrets); RDS secret ARN for retrieval |

## Validate only (safe, no apply)

```
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

The `.github/workflows/terraform.yml` workflow runs exactly these checks on
manual dispatch and **never applies**.

## Cleanup

`terraform destroy` removes the resources (RDS uses `skip_final_snapshot = true`
and `deletion_protection = false` for demo convenience). Destroy is also
billable-while-running until complete; verify in the AWS console.

## Untested assumptions to verify

- EKS/Kubernetes version `1.30`, node AMI compatibility, and CNI behavior.
- `default.redis7` parameter group matching `redis_engine_version`.
- Security groups allow DB/Redis only from the VPC CIDR; tighten to node/pod
  security groups for real use.
- Subnet CIDR lists must have at least `az_count` entries.
- The k8s manifests in `deploy/k8s/` are a separate, also-untested scaffold; this
  Terraform does not deploy the app onto EKS (no Helm/kubectl step is included).

Nothing here has been benchmarked. All sizes are demo guesses, not measured
results.