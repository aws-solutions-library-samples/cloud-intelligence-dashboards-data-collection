---
inclusion: manual
---

# Module Creation Quick Reference

Quick checklist and common patterns for creating data collection modules.

## Quick Start

1. **Decide module type**: Determine if your module targets management accounts only or linked accounts
2. **Trigger the hook**: Use the "Create New Data Collection Module" hook from the Agent Hooks panel
3. **Or manually**: Copy `.kiro/steering/module-template.yaml` to `data-collection/deploy/module-<name>.yaml`
4. **Replace all TODO markers** with actual implementation
5. **Test deployment** in a development environment

## Module Type Selection

**CRITICAL**: Every module must use EITHER ManagementRoleName OR MultiAccountRoleName parameter, never both.

### Management Account Modules
Use `ManagementRoleName` for modules that:
- Collect organization-wide data
- Only run against the management/payer account
- Use organization-level APIs

Examples: Organizations, Consolidated Billing, Organization-level Trusted Advisor

```yaml
Parameters:
  ManagementRoleName:
    Type: String
    Description: The name of the IAM role that will be deployed in the management account

# In Lambda IAM policy:
Resource: !Sub "arn:${AWS::Partition}:iam::*:role/${ManagementRoleName}"

# In Lambda environment:
ROLE_NAME: !Ref ManagementRoleName

# In Step Function:
CollectionType: "Payers"
```

### Linked Account Modules
Use `MultiAccountRoleName` for modules that:
- Collect account-specific resources
- Run against all linked accounts
- Use account-level APIs

Examples: EC2 Inventory, RDS Usage, License Manager, Health Events

```yaml
Parameters:
  MultiAccountRoleName:
    Type: String
    Description: Name of the IAM role deployed in all accounts

# In Lambda IAM policy:
Resource: !Sub "arn:${AWS::Partition}:iam::*:role/${MultiAccountRoleName}"

# In Lambda environment:
ROLE_NAME: !Ref MultiAccountRoleName

# In Step Function:
CollectionType: "LINKED"
```

## Common AWS Service Patterns

### Services Requiring Specific Regions

Some AWS services only operate in specific regions:

```python
# License Manager - must use us-east-1
client = boto3.client(
    'license-manager',
    config=config,
    region_name="us-east-1",  # Required
    aws_access_key_id=cred['AccessKeyId'],
    aws_secret_access_key=cred['SecretAccessKey'],
    aws_session_token=cred['SessionToken'],
)
```

### Organization-Wide vs Account-Specific APIs

```python
# Check if using organization API or local account API
USE_ORG = 'local' != os.environ.get('API', 'org')

if USE_ORG:
    response = client.list_resources_for_organization(MaxResults=100)
else:
    response = client.list_resources(MaxResults=100)
```

### Pagination Patterns

```python
# Standard pagination with NextToken
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
```

### Error Handling for Missing Permissions

```python
try:
    data = client.get_resource(ResourceId=resource_id)
except client.exceptions.AccessDeniedException:
    logger.warning(f'AccessDenied for resource {resource_id}')
    continue
except Exception as exc:
    logger.error(f'Error processing resource {resource_id}: {exc}')
    raise
```

## IAM Role Patterns

### Management Account Role Pattern

```yaml
LambdaRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub "${ResourcePrefix}${CFDataName}-LambdaRole"
    Policies:
      - PolicyName: !Sub "${CFDataName}-ManagementAccount-LambdaRole"
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
            - Effect: "Allow"
              Action: "sts:AssumeRole"
              Resource: !Sub "arn:${AWS::Partition}:iam::*:role/${ManagementRoleName}"
```

### Linked Account Role Pattern

```yaml
LambdaRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub "${ResourcePrefix}${CFDataName}-LambdaRole"
    Policies:
      - PolicyName: !Sub "${CFDataName}-MultiAccount-LambdaRole"
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
            - Effect: "Allow"
              Action: "sts:AssumeRole"
              Resource: !Sub "arn:${AWS::Partition}:iam::*:role/${MultiAccountRoleName}"
```

## Common IAM Policies

### Read-Only Service Access

```yaml
- PolicyName: "ServiceAccess"
  PolicyDocument:
    Version: "2012-10-17"
    Statement:
      - Effect: "Allow"
        Action:
          - "service:List*"
          - "service:Describe*"
          - "service:Get*"
        Resource: "*"
```

### S3 Read/Write Access

```yaml
- PolicyName: "S3-Access"
  PolicyDocument:
    Version: "2012-10-17"
    Statement:
      - Effect: "Allow"
        Action:
          - "s3:PutObject"
          - "s3:GetObject"
        Resource:
          - !Sub "${DestinationBucketARN}/*"
      - Effect: "Allow"
        Action:
          - "s3:ListBucket"
        Resource:
          - !Sub "${DestinationBucketARN}"
```

### Step Function Execution

```yaml
- PolicyName: "StateMachineExecution"
  PolicyDocument:
    Version: "2012-10-17"
    Statement:
      - Effect: "Allow"
        Action: "states:StartExecution"
        Resource: !Sub "arn:${AWS::Partition}:states:${AWS::Region}:${AWS::AccountId}:stateMachine:${ResourcePrefix}${CFDataName}-StateMachine"
```

## Data Storage Patterns

### Single Data Type

```python
PREFIX = os.environ['PREFIX']
data = collect_data(client)

# Add payer_id and account_id to records
for record in data:
    record['payer_id'] = payer_id
    record['account_id'] = account_id

store_data_to_s3(data, 'main', payer_id, account_id)
```

### Multiple Data Types

```python
S3_TYPE1_PREFIX = os.environ['S3_TYPE1_PREFIX']
S3_TYPE2_PREFIX = os.environ['S3_TYPE2_PREFIX']

type1_data = collect_type1_data(client)
for record in type1_data:
    record['payer_id'] = payer_id
    record['account_id'] = account_id
store_data_to_s3(type1_data, S3_TYPE1_PREFIX, payer_id, account_id)

type2_data = collect_type2_data(client)
for record in type2_data:
    record['payer_id'] = payer_id
    record['account_id'] = account_id
store_data_to_s3(type2_data, S3_TYPE2_PREFIX, payer_id, account_id)
```

### File Naming and Partitioning

**S3 Path Structure**:
```
s3://bucket/module-name/module-name-data-type/
  year=2024/
    month=02/
      day=16/
        123456789012_987654321098_20240216.json
        123456789012_111222333444_20240216.json
```

**File Naming Format**: `payer_id_account_id_yyyymmdd.json`
- Example: `123456789012_987654321098_20240216.json`
- payer_id: Management/payer account ID
- account_id: Linked account ID (or same as payer_id for management account)
- yyyymmdd: Date in compact format

**Partitioning**: Date-based only (year/month/day)
- Partitions are directories in S3
- Payer ID and account ID are stored as columns in the data
- Enables efficient date-range queries
```

### Nested Data Structures

```python
# For complex nested data, flatten before storing
def flatten_data(items):
    flattened = []
    for item in items:
        base = {k: v for k, v in item.items() if not isinstance(v, (list, dict))}
        if 'nested_items' in item:
            for nested in item['nested_items']:
                combined = {**base, **nested}
                flattened.append(combined)
    return flattened
```

## Multiple Tables (Not Crawlers!)

**Important**: Do NOT use Glue crawlers unless absolutely necessary. Define tables manually with partition projection.

When collecting multiple data types, create one Athena table per type:

```yaml
Type1Table:
  Type: AWS::Glue::Table
  Properties:
    CatalogId: !Ref AWS::AccountId
    DatabaseName: !Ref DatabaseName
    TableInput:
      Name: !Sub '${CFDataName}_type1'
      Description: !Sub 'Table for ${CFDataName} type1 data'
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
        storage.location.template: !Sub 's3://${DestinationBucket}/${CFDataName}/${CFDataName}-type1/year=${!year}/month=${!month}/day=${!day}'
      PartitionKeys:
        - Name: year
          Type: int
        - Name: month
          Type: int
        - Name: day
          Type: int
      StorageDescriptor:
        Columns:
          - Name: payer_id
            Type: string
          - Name: account_id
            Type: string
          - Name: field1
            Type: string
          - Name: field2
            Type: int
        Location: !Sub 's3://${DestinationBucket}/${CFDataName}/${CFDataName}-type1/'
        InputFormat: org.apache.hadoop.mapred.TextInputFormat
        OutputFormat: org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat
        SerdeInfo:
          SerializationLibrary: org.openx.data.jsonserde.JsonSerDe
          Parameters:
            paths: 'payer_id,account_id,field1,field2'

Type2Table:
  Type: AWS::Glue::Table
  Properties:
    # Similar structure for type2
    # ...

# Update Step Function - NO crawlers needed
Crawlers: '[]'  # Empty array
```

### Why Manual Tables?

- **No crawler delays**: Data is immediately queryable
- **No crawler costs**: Save on Glue crawler execution costs
- **Predictable schema**: Version-controlled table definitions
- **Partition projection**: Automatic partition discovery without crawlers
- **Better performance**: No waiting for crawler runs
- **Simpler partitioning**: Date-based only, no account-level partitions

**Key Points**:
- Partitions are date-based: year/month/day
- Payer ID and account ID are stored as columns, not partitions
- Files are named: `payer_id_account_id_yyyymmdd.json`
- All records must include payer_id and account_id fields

## Defining Table Schemas

### Common Data Types

```yaml
Columns:
  # Strings
  - Name: id
    Type: string
  - Name: name
    Type: string
  
  # Numbers
  - Name: count
    Type: int
  - Name: amount
    Type: double
  - Name: timestamp
    Type: bigint
  
  # Booleans
  - Name: is_active
    Type: boolean
  
  # Complex types
  - Name: tags
    Type: array<struct<key:string,value:string>>
  - Name: metadata
    Type: map<string,string>
  - Name: nested_object
    Type: struct<field1:string,field2:int>
```

### Schema Best Practices

1. **Match your data structure**: Define columns that match your JSON output
2. **Use appropriate types**: Choose the right Athena data type for each field
3. **Handle nested data**: Use struct, array, or map for complex fields
4. **Update SerDe paths**: List all column names in the SerDe parameters
5. **Test queries**: Verify schema works with actual data

### Example: Complete Table Definition

```yaml
ResourceTable:
  Type: AWS::Glue::Table
  Properties:
    CatalogId: !Ref AWS::AccountId
    DatabaseName: !Ref DatabaseName
    TableInput:
      Name: !Sub '${CFDataName}_resources'
      Description: 'AWS resource inventory'
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
        storage.location.template: !Sub 's3://${DestinationBucket}/${CFDataName}/${CFDataName}-resources/year=${!year}/month=${!month}/day=${!day}'
      PartitionKeys:
        - Name: year
          Type: int
        - Name: month
          Type: int
        - Name: day
          Type: int
      StorageDescriptor:
        Columns:
          - Name: payer_id
            Type: string
          - Name: account_id
            Type: string
          - Name: resource_id
            Type: string
          - Name: resource_type
            Type: string
          - Name: resource_name
            Type: string
          - Name: region
            Type: string
          - Name: created_timestamp
            Type: bigint
          - Name: tags
            Type: array<struct<key:string,value:string>>
          - Name: properties
            Type: map<string,string>
        Location: !Sub 's3://${DestinationBucket}/${CFDataName}/${CFDataName}-resources/'
        InputFormat: org.apache.hadoop.mapred.TextInputFormat
        OutputFormat: org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat
        SerdeInfo:
          SerializationLibrary: org.openx.data.jsonserde.JsonSerDe
          Parameters:
            paths: 'payer_id,account_id,resource_id,resource_type,resource_name,region,created_timestamp,tags,properties'
```

## Environment Variables

### Standard Variables

Always included:
- `BUCKET_NAME` - S3 destination bucket
- `PREFIX` - Module name for S3 paths
- `ROLE_NAME` - Cross-account role name

### Optional Variables

Add as needed:
- `LOG_LEVEL` - Logging level (default: INFO)
- `MAX_RETRIES` - API retry attempts (default: 10)
- `EXTRA_PAUSE` - Sleep between API calls (default: 0)
- `API` - Use 'local' for account-specific APIs (default: 'org')

### Module-Specific Variables

```yaml
Environment:
  Variables:
    BUCKET_NAME: !Ref DestinationBucket
    PREFIX: !Ref CFDataName
    ROLE_NAME: !Ref ManagementRoleName
    S3_DATA_PREFIX: !Ref DataPrefix
    FILTER_PATTERN: !Ref FilterPattern
```

## Schedule Expressions

```yaml
# Daily
Schedule: "rate(1 day)"

# Weekly
Schedule: "rate(7 days)"

# Bi-weekly
Schedule: "rate(14 days)"

# Monthly
Schedule: "rate(30 days)"

# Specific time (UTC)
Schedule: "cron(0 2 * * ? *)"  # 2 AM daily
```

## Collection Types

### Payers (Management Accounts Only)

```yaml
CollectionType: "Payers"
```

Use for:
- Organization-wide data
- Consolidated billing information
- Management account resources

### LINKED (All Accounts)

```yaml
CollectionType: "LINKED"
```

Use for:
- Account-specific resources
- Distributed data collection
- Per-account metrics

## Testing Commands

```bash
# Validate CloudFormation template
aws cloudformation validate-template \
  --template-body file://data-collection/deploy/module-<name>.yaml

# Deploy to test environment
aws cloudformation create-stack \
  --stack-name test-module-<name> \
  --template-body file://data-collection/deploy/module-<name>.yaml \
  --parameters file://test-parameters.json \
  --capabilities CAPABILITY_NAMED_IAM

# Trigger Step Function manually
aws stepfunctions start-execution \
  --state-machine-arn <step-function-arn> \
  --input '{"account": "{\"account_id\": \"123456789012\"}"}'

# Check Lambda logs
aws logs tail /aws/lambda/<function-name> --follow

# Test Athena query with partition projection
aws athena start-query-execution \
  --query-string "SELECT * FROM <database>.<table> WHERE year=2024 AND month=2 LIMIT 10" \
  --result-configuration OutputLocation=s3://your-results-bucket/

# Verify partitions are automatically discovered (no MSCK REPAIR needed)
aws athena start-query-execution \
  --query-string "SHOW PARTITIONS <database>.<table>" \
  --result-configuration OutputLocation=s3://your-results-bucket/
```

## Common Issues

### Issue: Lambda timeout
**Solution**: Increase timeout or implement batching

```yaml
Timeout: 900  # 15 minutes max
```

### Issue: Memory errors
**Solution**: Increase memory allocation

```yaml
MemorySize: 3008  # Up to 10GB available
```

### Issue: Rate limiting
**Solution**: Add EXTRA_PAUSE and implement exponential backoff

```python
EXTRA_PAUSE = float(os.environ.get('EXTRA_PAUSE', '0'))
if EXTRA_PAUSE > 0:
    time.sleep(EXTRA_PAUSE)
```

### Issue: Large data sets
**Solution**: Batch writes to S3

```python
def batch_store_data(data, prefix, account_id, batch_size=1000):
    for i in range(0, len(data), batch_size):
        batch = data[i:i+batch_size]
        store_data_to_s3(batch, f"{prefix}-batch-{i//batch_size}", account_id)
```

## File Locations

- **Module files**: `data-collection/deploy/module-*.yaml`
- **Step Function templates**: `data-collection/deploy/source/step-functions/`
- **Test files**: `test/`
- **Documentation**: `data-collection/README.md`

## Next Steps After Creation

1. Update main deployment templates to include new module
2. Add module to documentation
3. Create integration tests
4. Update CHANGELOG.md
5. Submit pull request with module description
