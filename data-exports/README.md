# Data Exports and Legacy CUR

## Table of Contents
- [Introduction](#introduction)
- [Data Exports](#data-exports)
  - [Basic Architecture](#basic-architecture-of-data-exports)
  - [Advanced Architecture](#advanced-architecture-of-data-exports)
- [Legacy Cost and Usage Report](#legacy-cost-and-usage-report)
- [FAQ](#faq)

## Introduction
This readme contains description of solutions for AWS Data Exports and Legacy CUR replication and consolidation across multiple accounts. This is a part of Cloud Intelligence Dashboards and it is recommended by [AWS Data Exports official documentation](https://docs.aws.amazon.com/cur/latest/userguide/dataexports-processing.html).

## Data Exports

For deployment instructions, please refer to the documentation at: https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html.

Check code here: [data-exports-aggregation.yaml](deploy/data-exports-aggregation.yaml)


### Basic Architecture of Data Exports
![Basic Architecture of Data Exports](/.images/architecture-data-exports.png  "Basic Architecture of Data Exports")

1. [AWS Data Exports](https://aws.amazon.com/aws-cost-management/aws-data-exports/) delivers daily Cost & Usage Report (CUR2) and other reports to an [Amazon S3 Bucket](https://aws.amazon.com/s3/) in the Management Account.
2. [Amazon S3](https://aws.amazon.com/s3/) replication rule copies Export data to a dedicated Data Collection Account S3 bucket automatically.
3. [Amazon Athena](https://aws.amazon.com/athena/) allows querying data directly from the S3 bucket using an [AWS Glue](https://aws.amazon.com/glue/) table schema definition.
4. [Amazon QuickSight](https://aws.amazon.com/quicksight/) datasets can read from [Amazon Athena](https://aws.amazon.com/athena/). Check Cloud Intelligence Dashboards for more details.

### Advanced Architecture of Data Exports
For customers with additional requirements, an enhanced architecture is available:

![Advanced Architecture of Data Exports](/.images/architecture-data-exports-advanced.png  "Advanced Architecture of Data Exports")

1. [AWS Data Exports](https://aws.amazon.com/aws-cost-management/aws-data-exports/) service delivers updated monthly [Cost & Usage Report (CUR2)](https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html) up to three times a day to an [Amazon S3](https://aws.amazon.com/s3/) Bucket in your AWS Account (either in Management/Payer Account or a regular Linked Account). In us-east-1 region, the CloudFormation creates native resources; in other regions, CloudFormation uses AWS Lambda and Custom Resource to provision Data Exports in us-east-1.

2. [Amazon S3 replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html) rules copy Export data to a dedicated Data Collection Account automatically. This replication filters out all metadata and makes the file structure on the S3 bucket compatible with [Amazon Athena](https://aws.amazon.com/athena/) and [AWS Glue](https://aws.amazon.com/glue/) requirements.

3. A [Bucket Policy](https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html) controls which accounts can replicate data to the destination bucket.

4. [AWS Glue Crawler](https://docs.aws.amazon.com/glue/latest/dg/components-overview.html#crawling-component) runs every midnight UTC to update the partitions of the table definition in [AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/components-overview.html#data-catalog-component).

5. [Amazon QuickSight](https://aws.amazon.com/quicksight/) pulls data from Amazon Athena to its SPICE (Super-fast, Parallel, In-memory Calculation Engine).

6. Updated QuickSight dashboards are available for the users.

7. When collecting data exports for Linked accounts (not for Management Accounts), you may also want to collect data exports for the Data Collection account itself. In this case, specify the Data Collection account as the first in the list of Source Accounts. Replication is still required to remove metadata.

8. Athena's reading process can be affected by writing operations. When replication arrives, it might fail to update datasets, especially with high volumes of data. In such cases, consider scheduling temporary disabling and re-enabling of the Amazon S3 bucket policy that allows replication. Since exports typically arrive up to three times a day, this temporary deactivation has minimal side effects and the updated data will be available with the next data delivery.

9. (Optional) Secondary bucket replication enables customers to archive data exports, consolidating data exports from multiple AWS Organisations or deploying staging environments (as described below ). 

### Using Secondary Replication Bucket
There can be various situations where customers need to replicate data exports to multiple destinations. One common scenario is a large enterprise with multiple business units, each with one or more AWS organisations. For this large enterprise, the Headquarters requires a consolidated view across all Business Units while simultaneously enabling individual Business Units to have visibility into their own data. 

To accomplish this, both the Headquarters and Business Unit can implement separate data export destination stacks. Business Unit administrators, working from their management account, can specify a target bucket located within the Headquarters stack, enabling seamless data replication to both S3 buckets.

Other scenario can be a replicating data to a staging environment for testing purposes. Please make sure that both destination accounts have the DataExport stack in the Destination configuration before updating Source account(s). 

![Secondary Replication Bucket](/.images/architecture-data-export-replication-to-secondary.png)

1. [AWS Data Exports](https://aws.amazon.com/aws-cost-management/aws-data-exports/) service delivers updated monthly [Cost & Usage Report (CUR2)](https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html) up to three times a day to an [Amazon S3](https://aws.amazon.com/s3/) Bucket in the Business Unit AWS Account (either in Management/Payer Account or a regular Linked Account). In us-east-1 region, the CloudFormation creates native resources; in other regions, CloudFormation uses AWS Lambda and Custom Resource to provision Data Exports in us-east-1.

2. [Amazon S3 replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html) rules copy Export data to a dedicated Data Collection Account automatically. This replication filters out all metadata and makes the file structure on the S3 bucket compatible with [Amazon Athena](https://aws.amazon.com/athena/) and [AWS Glue](https://aws.amazon.com/glue/) requirements.

3. Using the Secondary Replication rule, the Export data is replicated from Business Unit to the S3 bucket in the Headquarters AWS account. Each Business unit should create Secondary Replication rule to replicate the data to the S3 bucket in the Headquarters AWS account. This provides the Headquarter a consolidated data of all the Business Units. 

## Legacy Cost and Usage Report
Legacy AWS Cost and Usage Reports (Legacy CUR) can still be used for Cloud Intelligence Dashboards and other use cases.

The CID project provides a CloudFormation template for Legacy CUR. Unlike the Data Exports CloudFormation template, it does not provide AWS Glue tables. You can use this template to replicate CUR and aggregate CUR from multiple source accounts (Management or Linked).

![Basic Architecture of CUR](/.images/architecture-legacy-cur.png  "Basic Architecture of CUR")


Check code here: [cur-aggregation.yaml](deploy/cur-aggregation.yaml)

## FAQ

### Why replicate data instead of providing cross-account access?
Cross-account access is possible but can be difficult to maintain, considering the many different roles that require this access, especially when dealing with multiple accounts.

### We only have one AWS Organization. Do we still need this?
Yes. Throughout an organization's lifecycle, mergers and acquisitions may occur, so this approach prepares you for potential future scenarios.

### Can I use S3 Intelligent Tiering or S3 Infrequent Access (IA) for my CUR data connected to Athena?
We strongly recommend **against** using S3 IA for CUR data that is connected to Athena, especially if you have active FinOps users querying this data. Here's why:
- CUDOS typically only retrieves data for the last 7 months, so theoretically older data could be moved to S3 IA or managed with Intelligent Tiering.
- Moving older CUR parquet files to IA could potentially reduce storage costs by up to 45%.
- **However**, this only saves money if the data isn't frequently accessed. With S3 IA, you're charged $0.01 per GB retrieved.
- Athena uses multiple computational nodes in parallel, and complex queries can multiply data reads dramatically. For every 1GB of data you want to scan, Athena might perform up to 75GB of S3 reads.
- If someone runs a query without properly limiting it to specific billing periods, the retrieval costs can be astronomical. For example:
  * Scanning a full CUR of 600GB: `600GB × 75 × $0.01/GB` = `$450.00` for just one query!
- Due to this risk of human error, we do not use storage tiering as a default and strongly advise against it for CUR data connected to Athena.
We also advise agains Intelligent Tiering by default.
- KPI Dashboard - one of our foundational dashboards - scans the entire CUR (Cost and Usage Report) data to detect the first snapshot and determine its age. This prevents AWS Intelligent Tiering from functioning effectively, as it forces all data to remain in frequent access tiers and result is unnecessary additional monitoring costs with no cost-saving benefits.


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

**Use the public CloudFormation template:** [Cloud Intelligence Dashboards Deployment in Global Regions](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/deployment-in-global-regions.html)

**Key points:**
- Deploy from the **official public repository** (not this beta repository)
- Select a **different Data Collection Account** than your production environment
- This creates IAM roles, S3 buckets, and Glue databases needed for data collection
- Note the S3 bucket name and database name created - you'll need these for the next steps

#### Step 2: Prepare Your Environment

Before deploying the beta module, you need to upload the custom CloudFormation templates to an S3 bucket.

1. **Clone this repository:**
   ```bash
   git clone <this-repository-url>
   cd cloud-intelligence-dashboards-data-collection
   ```

2. **Create or use an existing S3 bucket** in your Data Collection Account for storing CloudFormation templates:
   ```bash
   # Create a new bucket (if needed)
   aws s3 mb s3://your-cfn-templates-bucket --region <your-region>
   
   # Enable versioning (recommended)
   aws s3api put-bucket-versioning \
     --bucket your-cfn-templates-bucket \
     --versioning-configuration Status=Enabled
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
   - Stack name: `cid-data-read-permissions-beta` (use a different name than production)
   
   d. **Parameters:**
   - **DataCollectionAccountId**: Your beta Data Collection Account ID
   - **RolePrefix**: `CID-DC-Beta-` (use a different prefix than production)
   
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
     - ✅ Set **IncludeRdsMultitenantModule** = `yes`
     - ❌ Set all other `Include*Module` parameters = `no`
   
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
