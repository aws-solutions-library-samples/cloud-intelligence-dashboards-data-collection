## CID Data Collection

### About

This projects demonstrates usage of AWS API for collecting various types of usage data.

For deployment and additional information reference to the [documentation](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html).

[![Documentation](/.images/documentation.svg)](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html)


### Architecture

![Architecture](/.images/architecture-data-collection-detailed.png)

1. [Amazon EventBridge](https://aws.amazon.com/eventbridge/) rule invokes [AWS Step Functions](https://aws.amazon.com/step-functions/) for every deployed data collection module based on schedule.
2. The Step Function launches a [AWS Lambda](https://aws.amazon.com/lambda/) function **Account Collector** that assumes **Read Role** in the Management accounts and retrieves linked accounts list via [AWS Organizations API](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_integrate_services.html).
3. Step Functions launches **Data Collection Lambda** function for each collected Account.
4. Each data collection module Lambda function assumes an [IAM](https://aws.amazon.com/iam/) role in linked accounts and retrieves respective optimization data via [AWS SDK for Python (Boto3)](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html). Retrieved data is aggregated in an [Amazon S3](https://aws.amazon.com/s3/) bucket.
5. Once data is stored in the S3 bucket, Step Functions trigger an [AWS Glue](https://aws.amazon.com/glue/) crawler which creates or updates the table in the [AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/components-overview.html#data-catalog-intro).
6. Collected data is visualized with the [Cloud Intelligence Dashboards](https://aws.amazon.com/solutions/implementations/cloud-intelligence-dashboards/) using [Amazon QuickSight](https://aws.amazon.com/quicksight/) to get optimization recommendations and insights.


### Modules
List of modules and objects collected:
| Module Name                  | AWS Services          | Collected In        | Details  |
| ---                          |  ---                  | ---                 | ---      |
| `organization`               | [AWS Organizations](https://aws.amazon.com/organizations/)     | Management Accounts  |          |
| `budgets`                    | [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/)           | Linked Accounts      |          |
| `compute-optimizer`          | [AWS Compute Optimizer](https://aws.amazon.com/compute-optimizer/) | Management Accounts  | Requires [Enablement of Compute Optimizer](https://aws.amazon.com/compute-optimizer/getting-started/#:~:text=Opt%20in%20for%20Compute%20Optimizer,created%20automatically%20in%20your%20account.) |
| `trusted-advisor`            | [AWS Trusted Advisor](https://aws.amazon.com/premiumsupport/technology/trusted-advisor/)   | Linked Accounts      | Requires Business, Enterprise or On-Ramp Support Level |
| `support-cases`              | [AWS Support](https://aws.amazon.com/premiumsupport/)           | Linked Accounts      | Requires Business, Enterprise On-Ramp, or Enterprise Support plan |
| `cost-explorer-cost-anomaly` | [AWS Cost Anomaly Detection](https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/)         | Management Accounts  |          |
| `cost-explorer-rightsizing`  | [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/)     | Management Accounts  | DEPRECATED. Please use `Data Exports` for `Cost Optimization Hub` |
| `inventory`                  | Various services      | Linked Accounts      | Collects `Amazon OpenSearch Domains`, `Amazon ElastiCache Clusters`, `RDS DB Instances`, `EBS Volumes`, `AMI`, `EC2 Instances`, `EBS Snapshot`, `RDS Snapshot`, `Lambda`, `RDS DB Clusters`, `EKS Clusters` |
| `pricing`                    | Various services      | Data Collection Account | Collects pricing for `Amazon RDS`, `Amazon EC2`, `Amazon ElastiCache`, `AWS Lambda`, `Amazon OpenSearch`, `AWS Compute Savings Plan` |
| `rds-usage`                  |  [Amazon RDS](https://aws.amazon.com/rds/)           | Linked Accounts      | Collects CloudWatch metrics for chargeback |
| `transit-gateway`            |  [AWS Transit Gateway](https://aws.amazon.com/transit-gateway/)  | Linked Accounts      | Collects CloudWatch metrics for chargeback |
| `ecs-chargeback`             |  [Amazon ECS](https://aws.amazon.com/ecs/)           | Linked Accounts      |  |
| `backup`                     |  [AWS Backup](https://aws.amazon.com/backup/)           | Management Accounts  | Collects Backup Restore and Copy Jobs. Requires [activation of cross-account](https://docs.aws.amazon.com/aws-backup/latest/devguide/manage-cross-account.html#enable-cross-account) |
| `health-events`              |  [AWS Health](https://aws.amazon.com/health/) | Management Accounts  | Collect AWS Health notifications via AWS Organizational view  |
| `licence-manager`            |  [AWS License Manager](https://aws.amazon.com/license-manager/)  | Management Accounts  | Collect Licenses and Grants |
| `aws-feeds`                  |  N/A                  | Data Collection Account | Collects Blog posts and News Feeds |
| `quicksight`                 |  [Amazon QuickSight](https://aws.amazon.com/quicksight/)    | Data Collection Account | Collects QuickSight User and Group information in the Data Collection Account only |
| `resilience-hub`                 |   [AWS Resilince Hub](https://aws.amazon.com/resilience-hub/) | Linked Accounts |  |
| `reference`                 |   Various services      | Data Collection Account | Collects reference data for other modules and dashboard to function |
| `rds-multitenant`           |  [Amazon RDS](https://aws.amazon.com/rds/) | Data Collection Account | Collects CloudWatch Database Insights metrics for multi-tenant RDS instances to enable cost allocation by tenant |

### Deployment Overview

![Deployment Architecture](/.images/architecture-data-collection-deploy.png)

1. Deploy the Advanced Data Collection Permissions CloudFormation stack to Management (Payer) AWS Account. The Permissions CloudFormation stack in the Management (Payer) Account also deploys Permissions stacks to each of Linked accounts via StackSets.

2. Deploy the Data Collection Stack to the Data Collection AWS Account


For deployment and further information please reference to this [documentation](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html).

[![Documentation](/.images/documentation.svg)](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html)

### Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md)
## RDS Multi-Tenant Module (Beta)

### Overview
The RDS Multi-Tenant module enables cost allocation for multi-tenant RDS workloads by collecting Performance Insights metrics grouped by various dimensions (user, database, host, SQL queries, and wait events). This allows you to attribute RDS costs to individual tenants, databases, or specific SQL queries.

### Beta Deployment Instructions

> **⚠️ Important Beta Considerations**
> 
> This is a beta feature. To ensure safe testing without affecting your existing production environment:
> 
> 1. **Create a new CID Foundation Stack** - Deploy a separate data collection infrastructure for this beta
> 2. **Use a different Data Collection Account** - Select a new account dedicated to beta testing
> 3. **Do not update your existing CID stack** - Keep your production data collection stack unchanged
> 4. **Deploy only the RDS Multi-Tenant module** - Uncheck all other modules during deployment

#### Prerequisites

1. **RDS instances with Performance Insights enabled** across your AWS Organization
2. **A new AWS account** designated as the Data Collection Account for beta testing
3. **IAM roles configured** for cross-account access (created by the Foundation Stack)

#### Step 1: Deploy the CID Foundation Stack (New Instance)

Deploy a **new** CID Foundation Stack in your designated beta Data Collection Account using the **public repository**. This creates the necessary infrastructure without affecting your existing production setup.

**Follow the instructions provided in the public documentation:** [Cloud Intelligence Dashboards Deployment in Global Regions](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/deployment-in-global-regions.html)

**When deploying the stacks:**
- In Step 1
   - Choose a **different Data Collection Account** than the one you already use for your CID deployment.
   - Change the Resource Prefix value from the default ("cid") to a different value e.g. "rds-data"
   - Insert your management account ID(s) in "Source Account Ids"
   - Leave the other options at their default value
- In Step 2
   - Use the same Data Collection account as in step 1
   - Use the same Resource Prefix value as in step 1, e.g. "rds-data"
   - Leave the other options at their default value

#### Step 2: Prepare Your Environment

Before deploying the beta module, you need to upload the custom CloudFormation templates to an S3 bucket.

1. **Clone this repository:**
   ```bash
   git clone -b add-rds-multitenant-module --single-branch https://github.com/davidecoccia/cloud-intelligence-dashboards-data-collection.git
   cd cloud-intelligence-dashboards-data-collection
   ```

2. **Create or use an existing S3 bucket** in your Data Collection Account for storing CloudFormation templates:
   ```bash
   # Create a new bucket (if needed)
   aws s3 mb s3://your-cfn-templates-bucket --region <your-region>
   ```

#### Step 3: Deploy Read Permissions Stack (Management Account)

Deploy the read permissions stack in your **Management Account** to allow the Data Collection Account to access RDS Performance Insights data.

> **⚠️ Important:** If you already have a read permissions stack from your production CID deployment, create a **new stack with a different name** for this beta. Do not update your existing production stack.

1. **Switch to your Management Account** (where your AWS Organization is managed)

2. **Deploy via AWS CloudFormation Console:**
   
   a. Navigate to **CloudFormation** → **Create stack** → **With new resources**
   
   b. **Specify template:**
   - Choose **Upload a template file**
   - Upload: `data-collection/deploy/deploy-data-read-permissions.yaml` from the cloned repository
   
   c. **Stack details:**
   - Stack name: `cid-data-read-permissions-beta` (use a different name than the one in CID)
   
   d. **Parameters:**
   - **DataCollectionAccountId**: Your beta Data Collection Account ID
   - **RolePrefix**: `CID-DC-Beta-` (use a different prefix)
   
   e. **Configure stack options:** (use defaults or customize as needed)
   
   f. **Review and create:** Acknowledge IAM resource creation and click **Submit**

3. **Alternative: Deploy via AWS CLI:**
   ```bash
   aws cloudformation create-stack \
     --stack-name cid-data-read-permissions-beta \
     --template-body file://data-collection/deploy/deploy-data-read-permissions.yaml \
     --parameters \
       ParameterKey=DataCollectionAccountId,ParameterValue=<your-data-collection-account-id> \
       ParameterKey=RolePrefix,ParameterValue=CID-DC-Beta- \
     --capabilities CAPABILITY_NAMED_IAM \
     --region <your-region>
   ```

4. **Wait for stack creation to complete** and note the IAM role name created (it will be `CID-DC-Beta-Optimization-Data-Multi-Account-Role`)

#### Step 4: Deploy Data Collection Stack (Data Collection Account)

Deploy the Data Collection Stack with **only** the RDS Multi-Tenant module enabled in your **beta Data Collection Account**.

1. **Switch to your Data Collection Account**

2. **Upload the RDS Multi-Tenant module template to S3:**
   ```bash
   aws s3 cp data-collection/deploy/module-rds-multitenant.yaml \
     s3://your-cfn-templates-bucket/cfn/data-collection/v3.12.1/module-rds-multitenant.yaml \
     --region <your-region>
   ```

3. **Update the main template** to reference your S3 bucket:
   
   Edit `data-collection/deploy/deploy-data-collection.yaml` and find the `RdsMultitenantModule` section (around line 1540). Update the `TemplateURL` to point to your S3 bucket:
   ```yaml
   RdsMultitenantModule:
     Type: AWS::CloudFormation::Stack
     Condition: DeployRdsMultitenantModule
     Properties:
       TemplateURL: !Sub "https://your-cfn-templates-bucket.s3.${AWS::Region}.amazonaws.com/cfn/data-collection/v3.12.1/module-rds-multitenant.yaml"
   ```

4. **Package and upload the main template:**
   ```bash
   aws cloudformation package \
     --template-file data-collection/deploy/deploy-data-collection.yaml \
     --s3-bucket your-cfn-templates-bucket \
     --s3-prefix cloudformation-templates \
     --output-template-file packaged-template.yaml \
     --region <your-region>
   ```

5. **Deploy the stack:**

   **Option A: Using AWS CLI (Recommended)**
   ```bash
   aws cloudformation deploy \
     --template-file packaged-template.yaml \
     --stack-name cid-data-collection-rds-multitenant-beta \
     --parameter-overrides \
       DatabaseName=optimization_data \
       DestinationBucket=<bucket-from-step-1> \
       ManagementAccountID=<your-management-account-id> \
       MultiAccountRoleName=CID-DC-Beta-Optimization-Data-Multi-Account-Role \
       Schedule="rate(1 hour)" \
       ScheduleFrequent="rate(1 day)" \
       RegionsInScope=<your-regions> \
       ResourcePrefix=CID-DC- \
       CFNSourceBucket=aws-managed-cost-intelligence-dashboards \
       IncludeRdsMultitenantModule=yes \
       IncludeAWSFeedsModule=no \
       IncludeCostAnomalyModule=no \
       IncludeInventoryCollectorModule=no \
       IncludeComputeOptimizerModule=no \
       IncludeEUCUtilizationModule=no \
       IncludeBackupModule=no \
       IncludeOrgDataModule=no \
       IncludeHealthEventsModule=no \
       IncludeTransitGatewayModule=no \
       IncludeISVFeedsModule=no \
       IncludeQuickSightModule=no \
       IncludeBudgetsModule=no \
       IncludeReferenceModule=no \
       IncludeECSChargebackModule=no \
       IncludeRDSUtilizationModule=no \
       IncludeSupportCasesModule=no \
       IncludeServiceQuotasModule=no \
       IncludeRightsizingModule=no \
       IncludeTAModule=no \
       IncludeLicenseManagerModule=no \
       IncludeResilienceHubModule=no \
       ManagementAccountRole=Lambda-Assume-Role-Management-Account \
       EUCAccountIDs="*" \
       DataBucketsKmsKeysArns="" \
     --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
     --region <your-region>
   ```

   **Option B: Using AWS CloudFormation Console**
   
   a. Navigate to **CloudFormation** → **Create stack** → **With new resources**
   
   b. **Specify template:**
   - Choose **Upload a template file**
   - Upload: `packaged-template.yaml` (created in step 4)
   
   c. **Stack details:**
   - Stack name: `cid-data-collection-rds-multitenant-beta`
   
   d. **Parameters:**
   - **Module Selection:**
     - Set **IncludeRdsMultitenantModule** = `yes` and all other `Include*Module` parameters = `no`
   
   - **Key Parameters:**
     - **ManagementAccountID**: Your AWS Organization management account ID
     - **MultiAccountRoleName**: `CID-DC-Beta-Optimization-Data-Multi-Account-Role` (from Step 3)
     - **DestinationBucket**: The S3 bucket name from Step 1 (without `s3://` prefix)
     - **DatabaseName**: `optimization_data` (or the database name from Step 1)
     - **RegionsInScope**: Comma-delimited list (e.g., `us-east-1,eu-west-1,ap-northeast-1`)
     - **Schedule**: `rate(1 hour)` (or your preferred frequency)
     - **ResourcePrefix**: `CID-DC-`
     - **CFNSourceBucket**: `aws-managed-cost-intelligence-dashboards`
   
   - **RDS Multi-Tenant Specific Parameters:**
     - **DimensionsToTrack**: `user,database,host,sql,waits` (default, or customize)
   
   e. **Configure stack options:** (use defaults or customize as needed)
   
   f. **Review and create:** 
   - Acknowledge IAM resource creation
   - Click **Submit**

6. **Wait for stack creation to complete** (this may take 5-10 minutes)

#### Step 5: Verify Deployment

After deployment completes:

1. **Check the Step Function execution:**
   ```bash
   aws stepfunctions list-executions \
     --state-machine-arn <your-state-machine-arn> \
     --region <your-region>
   ```

2. **Verify data collection in S3:**
   ```bash
   aws s3 ls s3://<your-bucket>/rds_pi_data/ --recursive
   ```

3. **Query the Glue table:**
   ```sql
   SELECT dimension_type, COUNT(*) as count, SUM(value) as total_load
   FROM rds_performance_insights_db.hourly_rds_multitenant
   WHERE timestamp >= current_timestamp - interval '1' hour
   GROUP BY dimension_type
   ```

4. **Check the Athena view:**
   ```sql
   SELECT * FROM rds_performance_insights_db.pi_data_view
   LIMIT 10
   ```

#### Data Schema

The module creates the following resources:

**Glue Database:** `rds_performance_insights_db`

**Glue Table:** `hourly_rds_multitenant`
- Columns: `metric`, `resourcearn`, `instance_id`, `engine`, `num_vcpus`, `dimension_type`, `timestamp`, `value`
- Dimension-specific columns: `db_user_name`, `db_database_name`, `db_host_name`, `db_sql_statement`, `db_wait_event_name`, etc.
- Partitioned by: `payer_id`, `account_id`, `region`, `year`, `month`, `day`, `hour`

**Athena View:** `pi_data_view`
- Pre-aggregated metrics with calculated utilization percentages
- Columns include: `timestamp`, `account_id`, `resourcearn`, `engine`, `dimension_type`, `db_load`, `total_db_load`, `perc_utilization`

#### Cost Allocation Examples

**By User/Tenant:**
```sql
SELECT 
    db_user_name as tenant,
    SUM(value) as total_load,
    SUM(value) / MAX(total_db_load) * 100 as percent_of_total
FROM rds_performance_insights_db.pi_data_view
WHERE dimension_type = 'user'
    AND timestamp >= current_date - interval '7' day
GROUP BY db_user_name
ORDER BY total_load DESC
```

**By Database:**
```sql
SELECT 
    database_name,
    SUM(db_load) as total_load,
    AVG(perc_utilization) as avg_utilization_pct
FROM rds_performance_insights_db.pi_data_view
WHERE dimension_type = 'database'
    AND timestamp >= current_date - interval '7' day
GROUP BY database_name
ORDER BY total_load DESC
```

**Top SQL Queries:**
```sql
SELECT 
    sql_statement,
    SUM(db_load) as total_load,
    COUNT(DISTINCT timestamp) as hours_active
FROM rds_performance_insights_db.pi_data_view
WHERE dimension_type = 'sql'
    AND timestamp >= current_date - interval '7' day
GROUP BY sql_statement
ORDER BY total_load DESC
LIMIT 20
```

#### Dimension Limitations by Engine

Not all dimensions are supported by all RDS engines:

| Dimension | PostgreSQL | MySQL | MariaDB | Oracle | SQL Server | DocumentDB |
|-----------|------------|-------|---------|--------|------------|------------|
| user      | ✅         | ✅    | ✅      | ✅     | ✅         | ❌         |
| database  | ✅         | ✅    | ✅      | ❌     | ❌         | ❌         |
| host      | ✅         | ✅    | ✅      | ✅     | ✅         | ✅         |
| sql       | ✅         | ✅    | ✅      | ✅     | ✅         | ❌         |
| waits     | ✅         | ✅    | ✅      | ✅     | ✅         | ❌         |

The module automatically skips unsupported dimensions for each engine.

#### Known Limitations (Beta)

1. **SQL Dimension Coverage**: The SQL dimension uses tokenized queries (parameters replaced with `?`) which provides ~100% coverage of SQL activity. Individual literal SQL statements may show lower coverage due to AWS Performance Insights thresholds.

2. **Performance Insights Requirements**: 
   - Performance Insights must be enabled on each RDS instance
   - Minimum retention period: 7 days (free tier)
   - Data collection frequency matches your configured schedule (default: hourly)

3. **Cost Considerations**:
   - Performance Insights API calls incur charges
   - More dimensions = more API calls and storage
   - Recommended: Start with `user,database` dimensions, add others as needed

4. **Data Latency**: 
   - Performance Insights data has ~5-10 minute delay
   - Hourly collection means cost allocation is available with ~1 hour lag

#### Troubleshooting

**No data appearing in tables:**
- Verify Performance Insights is enabled on RDS instances
- Check Step Function execution logs for errors
- Verify IAM roles have necessary permissions (`pi:GetResourceMetrics`, `rds:DescribeDBInstances`)
- Ensure regions in `RegionsInScope` match where your RDS instances are located

**SQL dimension shows lower totals than user/database:**
- This is expected behavior - use user or database dimensions for accurate cost allocation
- SQL dimension is best for identifying expensive queries, not total cost allocation

**Crawler fails to update table:**
- Check Glue crawler logs
- Verify S3 bucket permissions
- Ensure Parquet files are being written correctly

#### Feedback and Support

This is a beta feature. Please provide feedback through:
- GitHub Issues: [cloud-intelligence-dashboards](https://github.com/aws-samples/aws-cudos-framework-deployment)
- AWS Support (if you have a support plan)

**What to include in feedback:**
- RDS engine types and versions
- Number of instances and accounts
- Dimensions being tracked
- Any errors or unexpected behavior
- Feature requests or improvements
