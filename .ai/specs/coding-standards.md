# Coding Standards

This document captures the coding conventions and patterns observed across the Cloud Intelligence Dashboards (CID) data collection project. It serves as a reference for contributors and AI-assisted tooling.

---

## 1. CloudFormation Templates

### 1.1 Template Structure

Templates follow a consistent ordering:

1. `AWSTemplateFormatVersion: '2010-09-09'`
2. `Description` — brief, descriptive
3. `Parameters` — standard set first, then module-specific
4. `Conditions`
5. `Outputs`
6. `Resources`

### 1.2 Naming Conventions

- Module files: `module-<service-name>.yaml` (kebab-case)
- Resource prefix: all resource names use `!Sub "${ResourcePrefix}${CFDataName}-<ResourceType>"`
- Lambda functions: `!Sub '${ResourcePrefix}${CFDataName}-Lambda'`
- IAM roles: `!Sub "${ResourcePrefix}${CFDataName}-LambdaRole"`
- Step Functions: `!Sub '${ResourcePrefix}${CFDataName}-StateMachine'`
- Log groups: `!Sub "/aws/lambda/${LambdaFunction}"`
- Schedulers: `!Sub '${ResourcePrefix}${CFDataName}-RefreshSchedule'`

### 1.3 Standard Parameters

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

Role parameter — choose ONE based on module type:
- `ManagementRoleName` — for payer/management account modules
- `MultiAccountRoleName` — for linked account modules

### 1.4 Standard Conditions

```yaml
Conditions:
  NeedDataBucketsKms: !Not [ !Equals [ !Ref DataBucketsKmsKeysArns, "" ] ]
```

### 1.5 Standard Outputs

```yaml
Outputs:
  StepFunctionARN:
    Description: ARN for the module's Step Function
    Value: !GetAtt ModuleStepFunction.Arn
```

### 1.6 IAM Role Pattern

- Always include `AWSLambdaBasicExecutionRole` managed policy
- Use `!Sub "arn:${AWS::Partition}:iam::*:role/${RoleName}"` for cross-account assume role
- Conditional KMS policy using `!If [ NeedDataBucketsKms, ... ]`
- S3 write access scoped to `!Sub "${DestinationBucketARN}/*"`
- Suppress cfn_nag W28 with reason: "Need explicit name to identify role actions"

### 1.7 Lambda Function Resource Pattern

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

### 1.8 Log Group

```yaml
LogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: !Sub "/aws/lambda/${LambdaFunction}"
    RetentionInDays: 60
```

### 1.9 Step Function and Scheduler

- Step Functions use `STANDARD` type with shared execution role
- Definition loaded from S3 via `DefinitionS3Location`
- `CollectionType`: `"Payers"` for management modules, `"LINKED"` for linked account modules
- Scheduler uses `FLEXIBLE` mode with 30-minute window

### 1.10 Athena Tables

New modules should define manual Athena tables with partition projection instead of Glue crawlers. Some older modules still use crawlers.


---

## 2. Inline Lambda Functions (Python)

These standards apply to Python code embedded in CloudFormation templates via `Code.ZipFile`.

### 2.1 Module-Level Structure

Inline Lambda code follows this ordering:

1. Module docstring (optional but encouraged)
2. Standard library imports (os, json, logging, datetime, re)
3. Third-party imports (boto3, botocore)
4. Module-level constants from environment variables
5. Logger setup
6. Helper classes (e.g., DateTimeEncoder)
7. Utility functions (assume_role, s3_upload, etc.)
8. `lambda_handler(event, context)` — main entry point

### 2.2 Environment Variable Access

```python
BUCKET = os.environ["BUCKET_NAME"]
PREFIX = os.environ["PREFIX"]
ROLE_NAME = os.environ['ROLE_NAME']  # or ROLENAME depending on module
```

Constants are defined at module level, not inside functions.

### 2.3 Logger Setup

```python
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
```

- Always use `__name__` for the logger
- Default log level is `INFO`, configurable via `LOG_LEVEL` env var
- Use `getattr` pattern for safe level resolution

### 2.4 Cross-Account Role Assumption

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

### 2.5 Lambda Handler Pattern

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

### 2.6 S3 Upload Pattern

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

### 2.7 Error Handling

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

### 2.8 JSON Serialization

For datetime objects:

```python
class DateTimeEncoder(JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()
        return None
```

Or as a simple function:

```python
def json_converter(obj):
    if isinstance(obj, datetime.datetime):
        return obj.strftime("%Y-%m-%d %H:%M:%S")
    return obj
```

### 2.9 Data Collection Pattern

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

---

## 3. Pylint Configuration

The project uses a custom pylint runner (`utils/pylint.py`) that extracts inline Lambda code from CloudFormation templates and runs pylint with these disabled checks:

| Code   | Description                                      |
|--------|--------------------------------------------------|
| C0301  | Line too long                                    |
| C0103  | Invalid name of module                           |
| C0114  | Missing module docstring                         |
| C0116  | Missing function or method docstring             |
| W1203  | Use lazy % formatting (logging-fstring-interpolation) |
| W1201  | Use lazy % formatting (logging-not-lazy)         |

Additionally, bandit security scanning skips:

| Code | Description              |
|------|--------------------------|
| B101 | Assert                   |
| B108 | Hardcoded tmp directory  |

The project `.pylintrc` sets `max-line-length=200`.

---

## 4. Linting and Security Scanning

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

---

## 5. Testing

### 5.1 Framework

- pytest with `minversion = 6.0`
- CLI logging enabled at INFO level
- Test directory: `test/`
- Run integration tests: `./test/run-test-from-scratch.sh --no-teardown`

### 5.2 Dependencies

```bash
pip3 install -U boto3 pytest cfn-flip pylint bandit cfn-lint checkov
```

---

## 6. General Python Conventions

- Python 3.9+ required (Lambda runtime: python3.13)
- Always use `encoding='utf-8'` with `open()` calls
- Use f-strings for string formatting in application code (allowed in inline Lambda per pylint config)
- Use lazy `%s` formatting in logging calls for standalone scripts
- Prefer `boto3.client()` over `boto3.resource()`
- Use `boto3.session.Session().get_partition_for_region()` for partition-aware ARN construction
- Temp files go in `/tmp/` (Lambda constraint)
- JSONL format for data files (one JSON object per line, newline-delimited)

---

## 7. Shell Scripts

- Use `#!/bin/bash` shebang
- Document shellcheck suppressions with comments
- Use color-coded output for pass/fail reporting
- Exit with appropriate codes (0 for success, 1 for failure)

---

## 8. Git and Repository

- Main branch: `main`
- Use clear commit messages
- Focus PRs on specific changes — do not reformat unrelated code
- Run `./utils/lint.sh` and `python3 ./utils/pylint.py` before submitting PRs
- Install and configure git-secrets to prevent credential leaks
