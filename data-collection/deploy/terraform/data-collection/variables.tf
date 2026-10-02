variable "resource_prefix" {
  description = "Prefix to be used for all resources created by this module"
  type        = string
  default     = "CID-DC-"
}

variable "cfn_source_bucket" {
  description = "Name of the S3 bucket where CloudFormation templates are stored"
  type        = string
  default     = "aws-managed-cost-intelligence-dashboards"
}

variable "destination_bucket" {
  description = "Name of the S3 bucket where data will be stored"
  type        = string
  default     = "cid-data-"
}

variable "management_account_id" {
  description = "Comma-delimited list of Account IDs for Management Account IDs"
  type        = string
}

variable "management_account_role" {
  description = "Management account role"
  type        = string
  default     = "Lambda-Assume-Role-Management-Account"
}

variable "multi_account_role_name" {
  description = "Multi Account Role Name"
  type        = string
  default     = "Optimization-Data-Multi-Account-Role"
}

variable "regions_in_scope" {
  description = "Comma-delimited list of AWS regions for resource data collection (e.g., \"us-east-1,eu-west-1,ap-northeast-1\")"
  type        = string
}

variable "data_buckets_kms_keys_arns" {
  description = "ARNs of KMS Keys for data buckets and/or Glue Catalog. Comma separated list, no spaces. Keep empty if data Buckets and Glue Catalog are not Encrypted with KMS. You can also set it to '*' to grant decrypt permission for all the keys."
  type        = string
}

variable "schedule" {
  description = "Cron expression for execution schedule.\")"
  type        = string
  default     = "rate(14 days)"
}

variable "schedule_frequent" {
  description = "Cron expression for more frequent executions.\")"
  type        = string
  default     = "rate(1 day)"
}

variable "database_name" {
  description = "Name of the Glue Database to be created"
  type        = string
  default     = "optimization_data"
}

variable "include_ta_module" {
  description = "Whether to include the Trusted Advisor module"
  type        = bool
  default     = true
}

variable "include_rds_usage_module" {
  description = "Whether to include the RDS Usage module"
  type        = bool
  default     = true
}

variable "include_org_data_module" {
  description = "Whether to include the Organization Data module"
  type        = bool
  default     = true
}

variable "include_ce_rightsizing_module" {
  description = "Whether to include the Cost Explorer Rightsizing module"
  type        = bool
  default     = true
}

variable "include_cost_anomaly_module" {
  description = "Whether to include the Cost Anomaly module"
  type        = bool
  default     = true
}

variable "include_support_cases_module" {
  description = "Whether to include the Support Cases module"
  type        = bool
  default     = true
}

variable "include_backup_module" {
  description = "Whether to include the Backup module"
  type        = bool
  default     = true
}

variable "include_inventory_module" {
  description = "Whether to include the Inventory module"
  type        = bool
  default     = true
}

variable "include_pricing_module" {
  description = "Whether to include the Pricing module"
  type        = bool
  default     = true
}

variable "include_compute_optimizer_module" {
  description = "Whether to include the Compute Optimizer module"
  type        = bool
  default     = true
}

variable "include_ecs_chargeback_module" {
  description = "Whether to include the ECS Chargeback module"
  type        = bool
  default     = true
}

variable "include_budgets_module" {
  description = "Whether to include the Budgets module"
  type        = bool
  default     = true
}

variable "include_transit_gateway_module" {
  description = "Whether to include the Transit Gateway module"
  type        = bool
  default     = true
}

variable "include_aws_feeds_module" {
  description = "Whether to include the AWS Feeds module"
  type        = bool
  default     = true
}

variable "include_health_events_module" {
  description = "Whether to include the Health Events module"
  type        = bool
  default     = true
}

variable "include_license_manager_module" {
  description = "Whether to include the License Manager module"
  type        = bool
  default     = true
}

variable "include_service_quotas_module" {
  description = "Whether to include the Service Quotas module"
  type        = bool
  default     = true
}

variable "include_quicksight_module" {
  description = "Whether to include the QuickSight module"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to be added to all resources"
  type        = map(string)
  default     = {}
}

variable "tag_version" {
  description = "GitHub tag version using for the deployment (e.g. 4.0.7)"
  type        = string
  default     = ""
}

validation {
  condition     = var.tag_version == "" || can(regex("^\\d+\\.\\d+\\.\\d+$", var.tag_version))
  error_message = "The tag_version must be in the format X.Y.Z where X, Y, and Z are digits (e.g., 4.0.7)"
}