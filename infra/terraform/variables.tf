# CHIMERA Checkout Shield - input variables. SANDBOX ONLY. UNTESTED.
# NO hardcoded secrets. AWS credentials are resolved through the standard
# provider chain (environment variables, shared credentials/config file, or an
# attached IAM role). Optionally set aws_profile; never put access keys here.

variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-west-2"
}

variable "aws_profile" {
  description = "Optional named profile from the shared AWS config/credentials file. Null uses the default provider chain."
  type        = string
  default     = null
}

variable "project_name" {
  description = "Name prefix for resources."
  type        = string
  default     = "chimera-checkout"
}

variable "environment" {
  description = "Environment tag. This scaffold is sandbox/demo only."
  type        = string
  default     = "sandbox"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ used)."
  type        = list(string)
  default     = ["10.42.0.0/24", "10.42.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ used)."
  type        = list(string)
  default     = ["10.42.10.0/24", "10.42.11.0/24"]
}

variable "az_count" {
  description = "Number of availability zones to spread subnets across."
  type        = number
  default     = 2
}

variable "db_name" {
  description = "Initial PostgreSQL database name."
  type        = string
  default     = "chimera_db"
}

variable "db_username" {
  description = "PostgreSQL master username. The password is managed by RDS in Secrets Manager (manage_master_user_password), so no secret is stored in Terraform."
  type        = string
  default     = "chimera"
}

variable "db_instance_class" {
  description = "RDS instance class (demo-sized)."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GiB."
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "PostgreSQL engine version (compose uses postgres:15)."
  type        = string
  default     = "15"
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type (demo-sized)."
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_engine_version" {
  description = "Redis engine version (compose uses redis:7)."
  type        = string
  default     = "7.1"
}

variable "redis_num_cache_clusters" {
  description = "Number of cache clusters (nodes) in the replication group. >=2 enables automatic failover."
  type        = number
  default     = 2
}

variable "eks_cluster_version" {
  description = "Kubernetes control plane version."
  type        = string
  default     = "1.30"
}

variable "node_instance_types" {
  description = "EC2 instance types for the managed node group."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "node_desired_size" {
  description = "Desired node count."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum node count."
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum node count."
  type        = number
  default     = 3
}

variable "artifacts_bucket_name" {
  description = "Optional explicit S3 artifact bucket name. Null derives a name from project/environment/account id."
  type        = string
  default     = null
}

variable "tags" {
  description = "Extra tags applied to all resources."
  type        = map(string)
  default     = {}
}