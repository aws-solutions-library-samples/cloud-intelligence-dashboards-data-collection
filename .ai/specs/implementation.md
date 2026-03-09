# Implementation Guide

This document captures the architectural patterns, execution flows, and operational workflows used across the Cloud Intelligence Dashboards (CID) data collection project. For coding style and formatting rules, see [coding-standards.md](coding-standards.md).

---

## 1. Module Architecture

### 1.1 Module Types

Modules fall into two categories based on which AWS account they collect data from:

| Type | Role Parameter | CollectionType | Description |
|------|---------------|----------------|-------------|
| Payer (Management) | `ManagementRoleName` | `"Payers"` | Collects from the management/payer account (e.g., health-events, organization, cost-anomaly) |
| Linked | `MultiAccountRoleName` | `"LINKED"` | Collects from each linked/member account (e.g., budgets, inventory, backup) |

The module type determines:
- Which IAM role parameter the template declares
- The `CollectionType` substitution in the Step Function definition
- Whether the Step Function iterates over linked accounts or payer accounts

### 1.2 Standard Parameters

Every module template includes these standard parameters:

- `DatabaseName` (default: `optimization_data`)
- `DestinationBucket` — with S3 bucket name AllowedPattern
- `DestinationBucketARN`
- `CFDataName` — module identifier, default matches module name
- `GlueRoleARN`
- `Schedule` — EventBridge schedule expression
- `ResourcePrefix`
- `LambdaAnalyticsARN`
- `AccountCollectorLambdaARN`
- `CodeBucket`
- `StepFunctionTemplate`
- `StepFunctionExecutionRoleARN`
- `SchedulerExecutionRoleARN`
- `DataBucketsKmsKeysArns` (default: `""`)

Plus ONE role parameter based on module type:
- `ManagementRoleName` — for payer/management account modules
- `MultiAccountRoleName` — for linked account modules

### 1.3 IAM Role Pattern

- Always include `AWSLambdaBasicExecutionRole` managed policy
- Use `!Sub "arn:${AWS::Partition}:iam::*:role/${RoleName}"` for cross-account assume role
- Conditional KMS policy using `!If [ NeedDataBucketsKms, ... ]`
- S3 write access scoped to `!Sub "${DestinationBucketARN}/*"`
- Suppress cfn_nag W28 with reason: "Need explicit name to identify role actions"

### 1.4 Lambda Function Resource Pattern

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
        # inline Python code
    Handler: 'index.lambda_handler'
    MemorySize: 2688
    Timeout: 300
    Role: !GetAtt LambdaRole.Arn
    Environment:
      Variables:
        BUCKET_NAME: !Ref DestinationBucket
        PREFIX: !Ref CFDataName
        ROLE_NAME: !Ref MultiAccountRoleName  # or ManagementRoleName
```

Suppress cfn_nag:
- W89: "No need for VPC in this case"
- W92: "No need for simultaneous execution"

### 1.5 Step Function and Scheduler

- Step Functions use `STANDARD` type with shared execution role
- Definition loaded from S3 via `DefinitionS3Location`
- `CollectionType`: `"Payers"` for management modules, `"LINKED"` for linked account modules
- Scheduler uses `FLEXIBLE` mode with 30-minute window

### 1.6 Athena Tables

New modules should define manual Athena tables with partition projection instead of Glue crawlers. Some older modules still use crawlers.


---

## 2. Lambda Execution Patterns

### 2.1 Cross-Account Role Assumption

Standard pattern used across all modules:

```python
def assume_role(account_id, service, region):
    partition = boto3.session.Session().get_partition_for_region(region_name=region)
    cred = boto3.client('sts', region_name=region).assume_role(
        RoleArn=f"arn:{partition}:iam::{account_id}:role/{ROLE_NAME}",
        RoleSessionName="data_collection"
    )['Credentials']
    return boto3.client(
        service,
        aws_access_key_id=cred['AccessKeyId'],
        aws_secret_access_key=cred['SecretAccessKey'],
        aws_session_token=cred['SessionToken']
    )
```

- Always resolve partition dynamically via `get_partition_for_region`
- Session name: `"data_collection"`

### 2.2 Lambda Handler Flow

```python
def lambda_handler(event, context):  #pylint: disable=W0613
    logger.info(f"Event data {json.dumps(event)}")
    if 'account' not in event:
        raise ValueError(
            "Please do not trigger this Lambda manually."
            "Find the corresponding state machine in Step Functions and Trigger from there."
        )
    account = json.loads(event["account"])
    account_id = account["account_id"]
    payer_id = account["payer_id"]
    # ... collection logic
```

- `context` parameter is unused but required — suppress with `#pylint: disable=W0613`
- Always validate that `'account'` key exists in event
- Parse account from `event["account"]` as JSON string
- Extract `account_id`, `account_name`, `payer_id`

### 2.3 Data Collection Pattern

```python
with open(TMP_FILE, "w", encoding='utf-8') as f:
    for item in paginated_results:
        item['Account_ID'] = account_id
        item['Account_Name'] = account_name
        f.write(json.dumps(item, cls=DateTimeEncoder) + "\n")
```

- Write JSONL format (one JSON object per line)
- Always add `Account_ID` and `Account_Name` to each record
- Always specify `encoding='utf-8'` on file operations
- Use boto3 paginators for API calls that support pagination

### 2.4 S3 Upload Pattern

```python
def s3_upload(account_id, payer_id):
    if os.path.getsize(TMP_FILE) == 0:
        logger.info(f"No data in file for {PREFIX}")
        return
    key = datetime.datetime.now().strftime(
        f"{PREFIX}/{PREFIX}-data/payer_id={payer_id}/year=%Y/month=%m/filename-{account_id}.json"
    )
    boto3.client('s3').upload_file(TMP_FILE, BUCKET, key)
```

- Write to `/tmp/data.json` (Lambda writable path)
- Check file size before uploading
- S3 key includes date-based partitioning: `year=%Y/month=%m`
- File naming: `<prefix>-<account_id>.json`

### 2.5 Error Handling Strategy

```python
except Exception as exc:  #pylint: disable=broad-exception-caught
    if "AccessDenied" in str(exc):
        print(f'Failed to assume role {ROLE_NAME} in account {account_id}.')
    else:
        print(f'{exc}. Gracefully exiting from Lambda so we do not break all StepFunction Execution')
    return
```

- Broad exception catching is used intentionally to prevent Step Function failures
- Always suppress pylint with `#pylint: disable=broad-exception-caught`
- AccessDenied errors get specific messaging
- Other errors exit gracefully with logging

---

## 3. Data Storage and Partitioning

### 3.1 S3 Path Structure

```
s3://<bucket>/<prefix>/<prefix>-data/payer_id=<payer_id>/year=YYYY/month=MM/<filename>.json
```

For modules with detail data (e.g., health-events):
```
s3://<bucket>/<prefix>/<prefix>-detail-data/payer_id=<payer_id>/year=YYYY/month=MM/day=DD/<filename>.json
```

### 3.2 Partitioning Scheme

- `payer_id` — top-level partition by management account
- `year` / `month` — date-based partitioning (all modules)
- `day` — optional daily partitioning for high-volume modules
- Partition keys use Hive-style `key=value` format for Athena compatibility

### 3.3 File Format

- JSONL (newline-delimited JSON) — one record per line
- Each record enriched with `Account_ID` and `Account_Name`
- Datetime fields serialized via `DateTimeEncoder` or `json_converter`

---

## 4. Deployment Architecture

### 4.1 Template Hierarchy

```
deploy-data-collection.yaml          # Main orchestrator — deploys shared resources and nested module stacks
├── account-collector.yaml           # Account discovery
├── deploy-data-read-permissions.yaml
├── deploy-in-linked-account.yaml
├── deploy-in-management-account.yaml
└── module-*.yaml                    # Individual data collection modules (nested stacks)
```

The main template conditionally deploys each module based on user-selected parameters.

### 4.2 Lambda Layers

Lambda layers (e.g., boto3) are built and published separately from the main deployment:

1. Build: `./data-collection/deploy/layers/build-boto3-layer.sh` — creates the zip locally
2. Publish: `./data-collection/deploy/layers/publish-boto3-layer.sh` — uploads to S3 and publishes the layer
3. The layer ARN is passed as a parameter to modules that need it
4. Do NOT commit zip files to the repository

### 4.3 Release Process

```bash
# Lint and validate
./utils/lint.sh
python3 ./utils/pylint.py

# Run integration tests
./test/run-test-from-scratch.sh --no-teardown

# Release (CID Team only)
./data-collection/utils/release.sh
```

---

## 5. Linting and Validation Workflow

All CloudFormation templates are validated with three tools:

1. **checkov** — infrastructure security scanning (skipped checks documented in `utils/lint.sh`)
2. **cfn-lint** — CloudFormation linting
3. **cfn_nag_scan** — CloudFormation security scanning

Run all linters:
```bash
./utils/lint.sh
```

Run pylint on inline Lambda code:
```bash
python3 ./utils/pylint.py
```

### 5.1 Pylint Extraction

The custom pylint runner (`utils/pylint.py`) extracts inline Lambda code from CloudFormation templates into temporary files and runs pylint + bandit against them. This is the primary mechanism for validating inline Python code quality.

---

## 6. Testing

### 6.1 Framework

- pytest with `minversion = 6.0`
- CLI logging enabled at INFO level
- Test directory: `test/`

### 6.2 Integration Tests

```bash
./test/run-test-from-scratch.sh --no-teardown
```

Tests install stacks from scratch in a single account, verify Athena table presence, then optionally tear down. Use `--no-teardown` to keep resources for inspection.

### 6.3 Dependencies

```bash
pip3 install -U boto3 pytest cfn-flip pylint bandit cfn-lint checkov
```

---

## 7. Git and Contribution Workflow

- Main branch: `main`
- Use clear commit messages
- Focus PRs on specific changes — do not reformat unrelated code
- Run `./utils/lint.sh` and `python3 ./utils/pylint.py` before submitting PRs
- Install and configure [git-secrets](https://github.com/awslabs/git-secrets) to prevent credential leaks
- See [CONTRIBUTING.md](/CONTRIBUTING.md) and [data-collection/CONTRIBUTING.md](/data-collection/CONTRIBUTING.md) for full details
