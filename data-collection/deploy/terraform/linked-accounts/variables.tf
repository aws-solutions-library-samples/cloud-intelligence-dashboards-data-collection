variable "resource_prefix" {
  description = "Prefix for IAM resources"
  type        = string
}

variable "multi_account_role_name" {
  description = "Name of the multi-account IAM role"
  type        = string
}

variable "data_collection_account_id" {
  description = "AWS account ID where data collection occurs"
  type        = string
}

variable "allow_ta_module" {
  description = "Enable TA module permissions"
  type        = string
  default     = "no"
}

variable "allow_support_cases" {
  description = "Enable support cases permissions"
  type        = string
  default     = "no"
}

variable "allow_budgets_readonly" {
  description = "Enable budgets read-only permissions"
  type        = string
  default     = "no"
}

variable "allow_inventory_collection" {
  description = "Enable inventory collection permissions"
  type        = string
  default     = "no"
}

variable "allow_ecs_chargeback" {
  description = "Enable ECS chargeback permissions"
  type        = string
  default     = "no"
}

variable "allow_rds_utilization" {
  description = "Enable RDS utilization permissions"
  type        = string
  default     = "no"
}

variable "allow_transit_gateway" {
  description = "Enable Transit Gateway permissions"
  type        = string
  default     = "no"
}

variable "allow_service_quotas" {
  description = "Enable Service Quotas permissions"
  type        = string
  default     = "no"
}