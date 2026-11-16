# CHIMERA Checkout Shield - Terraform outputs. SANDBOX ONLY. UNTESTED.
# These expose resource identifiers/endpoints, NOT secrets. The RDS master
# password is retrieved from Secrets Manager via the emitted secret ARN.

output "region" {
  description = "AWS region in use."
  value       = var.region
}

output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet ids."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet ids."
  value       = aws_subnet.private[*].id
}

output "eks_cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "eks_node_group_name" {
  description = "Managed node group name."
  value       = aws_eks_node_group.this.node_group_name
}

output "rds_endpoint" {
  description = "RDS PostgreSQL connection endpoint (host:port)."
  value       = aws_db_instance.this.endpoint
}

output "rds_address" {
  description = "RDS PostgreSQL hostname."
  value       = aws_db_instance.this.address
}

output "rds_master_user_secret_arn" {
  description = "Secrets Manager ARN holding the RDS-managed master password. Retrieve it with the AWS CLI/SDK; it is not printed here."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "redis_reader_endpoint" {
  description = "ElastiCache Redis reader endpoint."
  value       = aws_elasticache_replication_group.this.reader_endpoint_address
}

output "artifacts_bucket_name" {
  description = "S3 artifact bucket name."
  value       = aws_s3_bucket.artifacts.bucket
}