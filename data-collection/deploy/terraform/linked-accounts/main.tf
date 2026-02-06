data "aws_region" "current" {}
data "aws_partition" "current" {}

# Lambda execution role for data collection
resource "aws_iam_role" "lambda_role" {
  name = "${var.resource_prefix}${var.multi_account_role_name}"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${var.data_collection_account_id}:root"
        }
      }
    ]
  })
}

# Conditional policies based on features enabled
resource "aws_iam_role_policy" "ta_policy" {
  count = var.allow_ta_module == "yes" ? 1 : 0
  name = "TAPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "support:DescribeTrustedAdvisorChecks",
          "support:DescribeTrustedAdvisorCheckResult"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "support_cases_policy" {
  count = var.allow_support_cases == "yes" ? 1 : 0
  name = "SupportCasesPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "support:DescribeCases"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "budgets_readonly_policy" {
  count = var.allow_budgets_readonly == "yes" ? 1 : 0
  name = "BudgetsReadOnlyPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "budgets:ViewBudget",
          "budgets:ListTagsForResource"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "inventory_collector_policy" {
  count = var.allow_inventory_collection == "yes" ? 1 : 0
  name = "InventoryCollectorPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeImages",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots",
          "ec2:DescribeVpcs",
          "ec2:DescribeRegions"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_chargeback_policy" {
  count = var.allow_ecs_chargeback == "yes" ? 1 : 0
  name = "ECSChargebackPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:ListClusters",
          "ecs:ListContainerInstances",
          "ecs:DescribeContainerInstances"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "rds_utilization_policy" {
  count = var.allow_rds_utilization == "yes" ? 1 : 0
  name = "RDSUtilizationPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "rds:DescribeDBInstances",
          "rds:DescribeDBClusters",
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "transit_gateway_policy" {
  count = var.allow_transit_gateway == "yes" ? 1 : 0
  name = "TransitGatewayPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeTransitGatewayAttachments",
          "cloudwatch:Describe*",
          "cloudwatch:Get*",
          "cloudwatch:List*"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "service_quotas_policy" {
  count = var.allow_service_quotas == "yes" ? 1 : 0
  name = "ServiceQuotasReadOnlyPolicy"
  role = aws_iam_role.lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "servicequotas:ListRequestedServiceQuotaChangeHistory",
          "servicequotas:GetServiceQuota",
          "servicequotas:GetAWSDefaultServiceQuota"
        ]
        Resource = "*"
      }
    ]
  })
}