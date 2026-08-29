data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  template_url = "https://aws-managed-cost-intelligence-dashboards-${data.aws_region.current.name}.s3.amazonaws.com/cfn/${var.tag_version}/data-collection/deploy-data-collection.yaml"
}

resource "aws_cloudformation_stack" "data_collection" {
  name = "${var.resource_prefix}data-collection"
  capabilities = [
    "CAPABILITY_NAMED_IAM",
    "CAPABILITY_AUTO_EXPAND"
  ]
  template_url = local.template_url

  parameters = {
    ResourcePrefix     = var.resource_prefix
    DatabaseName       = var.database_name
    DestinationBucket = var.destination_bucket
    ManagementAccountID = var.management_account_id
    ManagementAccountRole = var.management_account_role
    MultiAccountRoleName = var.multi_account_role_name
    Schedule = var.schedule
    ScheduleFrequent = var.schedule_frequent
    CFNSourceBucket = var.cfn_source_bucket
    RegionsInScope = var.regions_in_scope
    DatabaseName = var.database_name
    DataBucketsKmsKeysArns = var.data_buckets_kms_keys_arns
    IncludeTAModule   = var.include_ta_module ? "yes" : "no"
    IncludeRDSUtilizationModule = var.include_rds_usage_module ? "yes" : "no"
    IncludeOrgDataModule = var.include_org_data_module ? "yes" : "no"
    IncludeRightsizingModule = var.include_ce_rightsizing_module ? "yes" : "no"
    IncludeCostAnomalyModule = var.include_cost_anomaly_module ? "yes" : "no"
    IncludeSupportCasesModule = var.include_support_cases_module ? "yes" : "no"
    IncludeBackupModule = var.include_backup_module ? "yes" : "no"
    IncludeInventoryCollectorModule = var.include_inventory_module ? "yes" : "no"
    IncludeComputeOptimizerModule = var.include_compute_optimizer_module ? "yes" : "no"
    IncludeECSChargebackModule = var.include_ecs_chargeback_module ? "yes" : "no"
    IncludeBudgetsModule = var.include_budgets_module ? "yes" : "no"
    IncludeTransitGatewayModule = var.include_transit_gateway_module ? "yes" : "no"
    IncludeAWSFeedsModule = var.include_aws_feeds_module ? "yes" : "no"
    IncludeHealthEventsModule = var.include_health_events_module ? "yes" : "no"
    IncludeLicenseManagerModule = var.include_license_manager_module ? "yes" : "no"
    IncludeServiceQuotasModule = var.include_service_quotas_module ? "yes" : "no"
    IncludeQuickSightModule = var.include_quicksight_module ? "yes" : "no"
  }

  tags = var.tags
}
