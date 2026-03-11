---
inclusion: manual
---

# Data Collection Module Creation Guide

This guide provides standards and patterns for creating new data collection modules in the Cloud Intelligence Dashboards project.

## Module Structure Overview

All data collection modules follow a consistent CloudFormation template structure with these core components:

1. **Parameters** - Standard inputs for module configuration
2. **Conditions** - Logic for optional features (KMS encryption)
3. **Outputs** - Module Step Function ARN
4. **Resources** - Lambda, IAM roles, Step Functions, Scheduler, Athena Tables (if applicable), Glue crawlers (if necessary)

## Standard Parameters

Every module MUST include these parameters:

```yaml
Parameters:
  DatabaseName:
    Type: String
    Description: Name of the Athena database to be created to hold lambda information
    Default: optimization_data
  
  DestinationBucket:
    Type: String
    Description: Name of the S3 Bucket that exists or needs to be created to hold data
    AllowedPattern: (?=^.{3,63}$)(?!^(\d+\.)+\d+$)(^(([a-z0-9]|[a-z0-9][a-z0-9\-]*[a-z0-9])\.)*([a-z0-9]|[a-z0-9][a-z0-9\-]*[a-z0-9])$)
  
  DestinationBucketARN:
    Type: String
    Description: ARN of the S3 Bucket that exists or needs to be created to hold data
    
  CFDataName:
    Type: String
    Description: The name of what this cf is doing.
    Default: <module-name>  # e.g., "license-manager", "health-events"
  
  Schedule:
    Type: String
    Description: EventBridge Schedule to trigger the data collection
    Default: "rate(14 days)"  # Adjust based on data freshness needs
  
  ResourcePrefix:
    Type: String
    Description: This prefix will be placed in front of all roles created. Note you may wish to add a dash at the end to make more readable
  
  LambdaAnalyticsARN:
    Type: String
    Description: Arn of lambda for Analytics
  
  AccountCollectorLambdaARN:
    Type: String
    Description: Arn of the Account Collector Lambda
  
  CodeBucket:
    Type: String
    Description: Source code bucket
  
  StepFunctionTemplate:
    Type: String
    Description: S3 key to the JSON template for the StepFunction
  
  StepFunctionExecutionRoleARN:
    Type: String
    Description: Common role for Step Function execution
  
  SchedulerExecutionRoleARN:
    Type: String
    Description: Common role for module Scheduler execution
  
  DataBucketsKmsKeysArns:
    Type: String
    Description: "ARNs of KMS Keys for data buckets and/or Glue Catalog. Comma separated list, no spaces. Keep empty if data Buckets and Glue Catalog are not Encrypted with KMS. You can also set it to '*' to grant decrypt permission for all the keys."
    Default: ""
```


Every module MUST include only one of parameters. The module creation process musk ask up front it the module is going to be run against the management account or the linked accounts. For management only, use the role ManagementRoleName parameter. For linked-account modules, use the MultiAccountRoleName parameter:

```yaml  
  ManagementRoleName:
    Type: String
    Description: The name of the IAM role that will be deployed in the management account which can retrieve AWS Organization data. KEEP THE SAME AS WHAT IS DEPLOYED INTO MANAGEMENT ACCOUNT

  MultiAccountRoleName:
    Type: String
    Description: Name of the IAM role deployed in all accounts which can retrieve AWS Data.
```

### Module-Specific Parameters

## Optional Glue Crawler

This parameter is only needed if there will be a Glue crawler used for the module. Prompt the creator if GLue will be used or not.

```yaml
  GlueRoleARN:
    Type: String
    Description: Arn for the Glue Crawler role
```

Add additional parameters as needed for your module's specific data collection requirements (e.g., data prefixes, API endpoints, filters).

## Standard Conditions

```yaml
Conditions:
  NeedDataBucketsKms: !Not [ !Equals [ !Ref DataBucketsKmsKeysArns, "" ] ]
```

## Standard Outputs

```yaml
Outputs:
  StepFunctionARN:
    Description: ARN for the module's Step Function
    Value: !GetAtt ModuleStepFunction.Arn
```

## Lambda Function Structure

### IAM Role Pattern

```yaml
LambdaRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub "${ResourcePrefix}${CFDataName}-LambdaRole"
    AssumeRolePolicyDocument:
      Statement:
        - Action:
            - sts:AssumeRole
          Effect: Allow
          Principal:
            Service:
              - !Sub "lambda.${AWS::URLSuffix}"
      Version: 2012-10-17
    ManagedPolicyArns:
      - !Sub "arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    Path: /
    Policies:
      - PolicyName: !Sub "${CFDataName}-ManagementAccount-LambdaRole"
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
            - Effect: "Allow"
              Action: "sts:AssumeRole"
              Resource: !Sub "arn:${AWS::Partition}:iam::*:role/${ManagementRoleName}"
      - PolicyName: "S3-Access"
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
            - Effect: "Allow"
              Action:
                - "s3:PutObject"
              Resource:
                - !Sub "${DestinationBucketARN}/*"
      - !If
        - NeedDataBucketsKms
        - PolicyName: "KMS"
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: "Allow"
                Action:
                  - "kms:GenerateDataKey"
                Resource: !Split [ ',', !Ref DataBucketsKmsKeysArns ]
        - !Ref AWS::NoValue
  Metadata:
    cfn_nag:
      rules_to_suppress:
        - id: W28
          reason: "Need explicit name to identify role actions"
```

### Lambda Function Pattern

```yaml
LambdaFunction:
  Type: AWS::Lambda::Function
  Properties:
    FunctionName: !Sub '${ResourcePrefix}${CFDataName}-Lambda'
    Description: !Sub "Lambda function to retrieve ${CFDataName}"
    Runtime: python3.13
    Architectures: [x86_64]
    Code:
      ZipFile: |
        # Python code here
    Handler: 'index.lambda_handler'
    MemorySize: 2688
    Timeout: 600
    Role: !GetAtt LambdaRole.Arn
    Environment:
      Variables:
        BUCKET_NAME: !Ref DestinationBucket
        PREFIX: !Ref CFDataName
        ROLE_NAME: !Ref ManagementRoleName
  Metadata:
    cfn_nag:
      rules_to_suppress:
        - id: W89
          reason: "No need for VPC in this case"
        - id: W92
          reason: "No need for simultaneous execution"
```

### Lambda Code Structure

```python
import os
import json
import logging
import time
from datetime import date
import boto3
from botocore.config import Config

# Initialize AWS clients
s3 = boto3.client('s3')

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))

# Environment variables
BUCKET = os.environ['BUCKET_NAME']
ROLE = os.environ['ROLE_NAME']
PREFIX = os.environ['PREFIX']
MAX_RETRIES = int(os.environ.get('MAX_RETRIES', "10"))
EXTRA_PAUSE = float(os.environ.get('EXTRA_PAUSE', '0'))

config = Config(retries={"max_attempts": MAX_RETRIES, "mode": "adaptive"})

def store_data_to_s3(data, prefix, payer_id, account_id):
    """Store collected data to S3 with date-based partitioning"""
    if not data:
        logger.info("No data")
        return
    
    # Add payer_id and account_id to each record
    for record in data:
        record['payer_id'] = payer_id
        record['account_id'] = account_id
    
    json_data = "\n".join(json.dumps(entity) for entity in data)
    
    # File naming: payer_id_account_id_yyyymmdd.json
    today = date.today()
    filename = f"{payer_id}_{account_id}_{today.strftime('%Y%m%d')}.json"
    
    # S3 path: prefix/year=yyyy/month=mm/day=dd/filename
    key = today.strftime(f"{PREFIX}/{PREFIX}-{prefix}/year=%Y/month=%m/day=%d/{filename}")
    
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json_data,
        ContentType='application/json'
    )
    logger.info(f'File upload successful to s3://{BUCKET}/{key}')

def process_one_account(account_id, payer_id=None):
    """Process data collection for a single account"""
    if payer_id is None:
        payer_id = account_id  # Use account_id as payer_id if not provided
    
    region = boto3.session.Session().region_name
    partition = boto3.session.Session().get_partition_for_region(region_name=region)
    
    logger.debug('assuming role')
    cred = boto3.client('sts').assume_role(
        RoleArn=f"arn:{partition}:iam::{account_id}:role/{ROLE}",
        RoleSessionName="data_collection"
    )['Credentials']
    
    # Create service client with assumed credentials
    client = boto3.client(
        'service-name',  # Replace with actual AWS service
        config=config,
        region_name=region,
        aws_access_key_id=cred['AccessKeyId'],
        aws_secret_access_key=cred['SecretAccessKey'],
        aws_session_token=cred['SessionToken'],
    )
    
    # Collect and store data
    data = collect_data(client)
    store_data_to_s3(data, 'data-type', payer_id, account_id)
    
    # Add sleep if EXTRA_PAUSE is configured
    if EXTRA_PAUSE > 0:
        time.sleep(EXTRA_PAUSE)

def collect_data(client):
    """Collect data from AWS service with pagination"""
    results = []
    pagination_token = ''
    
    while True:
        params = {'MaxResults': 100}
        if pagination_token:
            params['NextToken'] = pagination_token
            
        response = client.list_resources(**params)
        results.extend(response.get('Resources', []))
        
        pagination_token = response.get('NextToken', '')
        if not pagination_token:
            break
    
    return results

def lambda_handler(event, context):
    """Main Lambda handler"""
    logger.info(f"Event data {json.dumps(event)}")
    
    if 'account' not in event:
        raise ValueError(
            "Please do not trigger this Lambda manually. "
            "Find the corresponding state machine in Step Functions and Trigger from there."
        )
    
    account = json.loads(event["account"])
    
    try:
        # Extract payer_id if available, otherwise use account_id
        payer_id = account.get("payer_id", account["account_id"])
        process_one_account(account["account_id"], payer_id)
    except Exception as exc:
        logging.error(f"{account['account_id']}: {exc}")
        raise
    
    return "Successful"
```

## CloudWatch Logs

```yaml
LogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: !Sub "/aws/lambda/${LambdaFunction}"
    RetentionInDays: 60
```

## Athena Table Definitions (Recommended Approach)

**Important**: Glue crawlers are NOT recommended for this project. Instead, define Athena tables manually with date-based partitioning for better performance and automation.

### Why Manual Tables Over Crawlers

- **Performance**: Crawlers are slow and resource-intensive
- **Cost**: Crawlers incur additional costs for each run
- **Reliability**: Manual schemas are predictable and version-controlled
- **Automation**: Date-based partitions can be added automatically without crawlers
- **Schema Control**: Explicit control over data types and column names

### Manual Table Pattern

Create one Athena table per data type with date-based partitioning:

```yaml
DataTable:
  Type: AWS::Glue::Table
  Properties:
    CatalogId: !Ref AWS::AccountId
    DatabaseName: !Ref DatabaseName
    TableInput:
      Name: !Sub '${CFDataName}_data'  # Replace 'data' with actual data type
      Description: !Sub 'Table for ${CFDataName} data collection'
      TableType: EXTERNAL_TABLE
      Parameters:
        classification: json
        projection.enabled: 'true'
        projection.year.type: integer
        projection.year.range: '2020,2030'
        projection.year.digits: '4'
        projection.month.type: integer
        projection.month.range: '1,12'
        projection.month.digits: '2'
        projection.day.type: integer
        projection.day.range: '1,31'
        projection.day.digits: '2'
        storage.location.template: !Sub 's3://${DestinationBucket}/${CFDataName}/${CFDataName}-data/year=${!year}/month=${!month}/day=${!day}'
      PartitionKeys:
        - Name: year
          Type: int
        - Name: month
          Type: int
        - Name: day
          Type: int
      StorageDescriptor:
        Columns:
          # TODO: Define your schema columns here
          - Name: payer_id
            Type: string
          - Name: account_id
            Type: string
          - Name: id
            Type: string
          - Name: name
            Type: string
          - Name: created_date
            Type: string
          # Add more columns as needed
        Location: !Sub 's3://${DestinationBucket}/${CFDataName}/${CFDataName}-data/'
        InputFormat: org.apache.hadoop.mapred.TextInputFormat
        OutputFormat: org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat
        SerdeInfo:
          SerializationLibrary: org.openx.data.jsonserde.JsonSerDe
          Parameters:
            paths: 'payer_id,account_id,id,name,created_date'  # TODO: Update with actual column names
```

### Partition Projection Benefits

The `projection.*` parameters enable automatic partition discovery without running crawlers:
- **projection.enabled**: Enables partition projection
- **projection.year/month/day.type**: Defines partition types
- **projection.*.range**: Defines valid ranges for partitions
- **storage.location.template**: Template for S3 paths with partition values

**Note**: Partitions are date-based only (year/month/day). Payer ID and account ID are stored as columns in the data, not as partitions.

### Multiple Tables Example

For modules with multiple data types:

```yaml
Type1Table:
  Type: AWS::Glue::Table
  Properties:
    CatalogId: !Ref AWS::AccountId
    DatabaseName: !Ref DatabaseName
    TableInput:
      Name: !Sub '${CFDataName}_type1'
      # ... configuration for type1

Type2Table:
  Type: AWS::Glue::Table
  Properties:
    CatalogId: !Ref AWS::AccountId
    DatabaseName: !Ref DatabaseName
    TableInput:
      Name: !Sub '${CFDataName}_type2'
      # ... configuration for type2
```

## Step Function

**Note**: Remove crawler references since we use manual table definitions with partition projection.

```yaml
ModuleStepFunction:
  Type: AWS::StepFunctions::StateMachine
  Properties:
    StateMachineName: !Sub '${ResourcePrefix}${CFDataName}-StateMachine'
    StateMachineType: STANDARD
    RoleArn: !Ref StepFunctionExecutionRoleARN
    DefinitionS3Location:
      Bucket: !Ref CodeBucket
      Key: !Ref StepFunctionTemplate
    DefinitionSubstitutions:
      AccountCollectorLambdaARN: !Ref AccountCollectorLambdaARN
      ModuleLambdaARN: !GetAtt LambdaFunction.Arn
      Crawlers: '[]'  # Empty array - no crawlers needed with partition projection
      CollectionType: "Payers"  # or "LINKED" for linked accounts
      Params: ''
      Module: !Ref CFDataName
      DeployRegion: !Ref AWS::Region
      Account: !Ref AWS::AccountId
      Prefix: !Ref ResourcePrefix
      Bucket: !Ref DestinationBucket
```

## Scheduler

```yaml
ModuleRefreshSchedule:
  Type: 'AWS::Scheduler::Schedule'
  Properties:
    Description: !Sub 'Scheduler for the ODC ${CFDataName} module'
    Name: !Sub '${ResourcePrefix}${CFDataName}-RefreshSchedule'
    ScheduleExpression: !Ref Schedule
    State: ENABLED
    FlexibleTimeWindow:
      MaximumWindowInMinutes: 30
      Mode: 'FLEXIBLE'
    Target:
      Arn: !GetAtt ModuleStepFunction.Arn
      RoleArn: !Ref SchedulerExecutionRoleARN
```

## Analytics Executor

```yaml
AnalyticsExecutor:
  Type: Custom::LambdaAnalyticsExecutor
  Properties:
    ServiceToken: !Ref LambdaAnalyticsARN
    Name: !Ref CFDataName
```

## Naming Conventions

- **File name**: `module-<service-name>.yaml` (kebab-case)
- **CFDataName default**: `<service-name>` (kebab-case)
- **Lambda function**: `${ResourcePrefix}${CFDataName}-Lambda`
- **IAM role**: `${ResourcePrefix}${CFDataName}-LambdaRole`
- **Crawlers**: `${ResourcePrefix}${CFDataName}-<data-type>-Crawler`
- **Step Function**: `${ResourcePrefix}${CFDataName}-StateMachine`
- **Scheduler**: `${ResourcePrefix}${CFDataName}-RefreshSchedule`

## Best Practices

1. **Error Handling**: Always wrap account processing in try-except blocks
2. **Logging**: Use structured logging with account IDs for traceability
3. **Pagination**: Always implement pagination for AWS API calls
4. **Retries**: Use botocore Config with adaptive retry mode
5. **Rate Limiting**: Support EXTRA_PAUSE environment variable for throttling
6. **S3 Partitioning**: Use `year/month/day` partition structure (REQUIRED)
7. **File Naming**: Use `payer_id_account_id_yyyymmdd.json` format (REQUIRED)
8. **Data Enrichment**: Add payer_id and account_id columns to all records
9. **Manual Tables**: Define Athena tables manually with partition projection (NO crawlers)
10. **Schema Definition**: Explicitly define all columns in table schema
11. **Security**: Use cfn_nag suppressions with clear reasons
12. **Documentation**: Include clear descriptions for all parameters and resources

## Collection Types

- **Payers**: Collect from management/payer accounts only
- **LINKED**: Collect from all linked accounts in the organization

## Schedule Recommendations

- **Daily**: `rate(1 day)` - For frequently changing data (health events, budgets)
- **Weekly**: `rate(7 days)` - For moderately changing data
- **Bi-weekly**: `rate(14 days)` - For slowly changing data (licenses, quotas)

## Testing Checklist

- [ ] Module deploys successfully via CloudFormation
- [ ] Lambda function can assume cross-account role
- [ ] Data is written to S3 with correct date-based partitioning
- [ ] Athena tables are created with partition projection enabled
- [ ] Athena queries work without running crawlers
- [ ] Step Function executes successfully
- [ ] Scheduler triggers on schedule
- [ ] Error handling works for missing permissions
- [ ] KMS encryption works when enabled
- [ ] Analytics executor registers module
- [ ] Table schema matches actual data structure
