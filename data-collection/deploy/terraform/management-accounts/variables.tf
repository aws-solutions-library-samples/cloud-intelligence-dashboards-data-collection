variable "resource_prefix" {
  description = "Prefix for IAM resources"
  type        = string 
  default     = "CID-DC-"
}

variable "management_account_role" {
  description = "Name of the management account IAM role" 
  type        = string
  default     = "Lambda-Assume-Role-Management-Account"
}

variable "data_collection_account_id" {
  description = "Account ID for data collection"
  type        = string
}

variable "backup_module" {
  description = "Enable AWS Backup module permissions"
  type        = string
  default     = "no"
}

variable "compute_optimizer_module" {
  description = "Enable Compute Optimizer module permissions"
  type        = string
  default     = "no"
}

variable "cost_anomaly_module" {
  description = "Enable Cost Anomaly Detection module permissions"
  type        = string
  default     = "no"
}

variable "support_cases_module" {
  description = "Enable AWS Support Cases module permissions"
  type        = string
  default     = "no"
}

variable "health_events_module" {
  description = "Enable AWS Health Events module permissions"
  type        = string
  default     = "no"
}

variable "rightsizing_module" {
  description = "Enable Rightsizing module permissions"
  type        = string
  default     = "no"
}

variable "license_manager_module" {
  description = "Enable License Manager module permissions"
  type        = string
  default     = "no"
}

variable "service_quotas_module" {
  description = "Enable Service Quotas module permissions"
  type        = string
  default     = "no"
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