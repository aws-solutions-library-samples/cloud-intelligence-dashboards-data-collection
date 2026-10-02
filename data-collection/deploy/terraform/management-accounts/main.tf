data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  template_url = "https://aws-managed-cost-intelligence-dashboards-${data.aws_region.current.name}.s3.amazonaws.com/cfn/${var.tag_version}/data-collection/deploy-in-management-account.yaml"
}

# Management account IAM role deployment
resource "aws_cloudformation_stack" "mgmt_read" {
  name = "${var.resource_prefix}mgmt-read"
  template_url = local.template_url
  capabilities = ["CAPABILITY_NAMED_IAM"]
  
  parameters = {
    ResourcePrefix = var.resource_prefix
    ManagementAccountRole = var.management_account_role
    DataCollectionAccountID = var.data_collection_account_id
    IncludeBackupModule = var.backup_module
    IncludeComputeOptimizerModule = var.compute_optimizer_module
    IncludeCostAnomalyModule = var.cost_anomaly_module
    IncludeSupportCasesModule = var.support_cases_module
    IncludeHealthEventsModule = var.health_events_module
    IncludeRightsizingModule = var.rightsizing_module
    IncludeLicenseManagerModule = var.license_manager_module
    IncludeServiceQuotasModule = var.service_quotas_module
  }
}