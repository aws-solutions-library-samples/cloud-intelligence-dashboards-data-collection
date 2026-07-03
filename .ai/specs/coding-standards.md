---
inclusion: always unless expressly excluded
---

# Coding Standards

This document captures the coding style rules and formatting conventions for the Cloud Intelligence Dashboards (CID) data collection project. For architectural patterns, execution flows, and operational workflows, see [implementation.md](implementation.md).

---

## 1. CloudFormation Templates

### 1.1 Template Structure Ordering

Templates follow a consistent section ordering:

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

### 1.3 Standard Conditions

```yaml
Conditions:
  NeedDataBucketsKms: !Not [ !Equals [ !Ref DataBucketsKmsKeysArns, "" ] ]
```

### 1.4 Standard Outputs

```yaml
Outputs:
  StepFunctionARN:
    Description: ARN for the module's Step Function
    Value: !GetAtt ModuleStepFunction.Arn
```

### 1.5 cfn_nag Suppression Patterns

Always include the reason comment:

```yaml
Metadata:
  cfn_nag:
    rules_to_suppress:
      - id: W28
        reason: "Need explicit name to identify role actions"
      - id: W89
        reason: "No need for VPC in this case"
      - id: W92
        reason: "No need for simultaneous execution"
```

### 1.6 Log Group

```yaml
LogGroup:
  Type: AWS::Logs::LogGroup
  Properties:
    LogGroupName: !Sub "/aws/lambda/${LambdaFunction}"
    RetentionInDays: 60
```

### 1.7 IAM Roles and Policies — Least Privilege

IAM policies must be scoped to the specific resources the role needs. Do not
grant account-wide or service-wide wildcards on data actions.

- **No wildcard resource on S3 data actions.** Never write
  `Resource: arn:aws:s3:::*` or `arn:aws:s3:::*/*` for `s3:GetObject` /
  `s3:ListBucket`. Scope to the specific bucket ARN(s) and, where the access is
  confined to a known key prefix, to that prefix (e.g. `${Bucket}/${Prefix}*`).
- **Customer-supplied bucket lists — use `Fn::ForEach`.** When the buckets are
  provided as a parameter (variable at deploy time), declare the parameter as
  `Type: CommaDelimitedList`, add `Transform: 'AWS::LanguageExtensions'`, and
  replicate one scoped `AWS::IAM::RolePolicy` per bucket with `Fn::ForEach`
  (see `module-inventory.yaml` and `module-pricing.yaml` for the pattern). Use
  the `&{Identifier}` form in the logical id so bucket names containing `.` or
  `-` are accepted. This is preferred over a single wildcard statement.

  ```yaml
  'Fn::ForEach::SourceReadPolicies':
    - Bucket
    - !Ref SourceBuckets            # Type: CommaDelimitedList
    - 'SourceReadPolicy&{Bucket}':
        Type: AWS::IAM::RolePolicy
        Properties:
          RoleName: !Ref LambdaRole
          PolicyName: !Sub "S3Read-${Bucket}"
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: [s3:ListBucket]
                Resource: [!Sub "arn:${AWS::Partition}:s3:::${Bucket}"]
              - Effect: Allow
                Action: [s3:GetObject]
                Resource: [!Sub "arn:${AWS::Partition}:s3:::${Bucket}/${Prefix}*"]
  ```

- **When a list is passed to a Lambda env var**, the parameter is a list, so
  join it back: `SOURCE_BUCKETS: !Join [ ',', !Ref SourceBuckets ]`.
- **cfn_nag `W11`/`W12` (wildcard resource) must not be suppressed to hide an
  avoidable wildcard.** Only suppress when the wildcard is genuinely
  unavoidable, and the `reason` must state why scoping is not possible.
- Grant only the specific actions required (e.g. `s3:GetObject`,
  `s3:ListBucket`) — do not use `s3:*` or `s3:Get*`.

---

## 2. Inline Lambda Functions (Python)

These standards apply to Python code embedded in CloudFormation templates via `Code.ZipFile`.

### 2.1 Module-Level Code Ordering

1. Module docstring (optional but encouraged)
2. Standard library imports (os, json, logging, datetime, re)
3. Third-party imports (boto3, botocore)
4. Module-level constants from environment variables
5. Logger setup
6. Custom functions
7. `lambda_handler(event, context)` — main entry point

### 2.2 Environment Variable Access Style

```python
BUCKET_NAME = os.environ["BUCKET_NAME"]
PREFIX = os.environ["PREFIX"]
ROLE_NAME = os.environ['ROLE_NAME']
```

Constants are defined at module level, not inside functions.

### 2.3 Logger Setup Style

```python
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
```

- Always use `__name__` for the logger
- Default log level is `INFO`, configurable via `LOG_LEVEL` env var
- Use `getattr` pattern for safe level resolution

### 2.4 Pylint Inline Suppressions

Standard inline suppressions used in Lambda code:

| Suppression | Where | Reason |
|-------------|-------|--------|
| `#pylint: disable=W0613` | `lambda_handler(event, context)` | `context` is unused but required by Lambda |
| `#pylint: disable=broad-exception-caught` | `except Exception as exc:` | Intentional — prevents Step Function failures |

---

## 3. Pylint Configuration

### 3.1 Project-Level Config

`.pylintrc` at project root:
```ini
[FORMAT]
max-line-length=200
```

### 3.2 Custom Pylint Runner Disabled Checks

The custom pylint runner (`utils/pylint.py`) disables these checks for inline Lambda code:

| Code   | Description                                      |
|--------|--------------------------------------------------|
| C0301  | Line too long                                    |
| C0103  | Invalid name of module                           |
| C0114  | Missing module docstring                         |
| C0116  | Missing function or method docstring             |
| W1203  | Use lazy % formatting (logging-fstring-interpolation) |
| W1201  | Use lazy % formatting (logging-not-lazy)         |

### 3.3 Bandit Security Scanning Skips

| Code | Description              |
|------|--------------------------|
| B101 | Assert                   |
| B108 | Hardcoded tmp directory  |

---

## 4. General Python Conventions

- Python 3.10+ required (Lambda runtime default: python3.13)
- Always use `encoding='utf-8'` with `open()` calls
- Use f-strings for string formatting in application code (allowed in inline Lambda per pylint config)
- Use lazy `%s` formatting in logging calls for standalone scripts
- Prefer `boto3.client()` over `boto3.resource()`
- Use `boto3.session.Session().get_partition_for_region()` for partition-aware ARN construction
- Temp files go in `/tmp/` (Lambda constraint)
- JSONL format for data files (one JSON object per line, newline-delimited)
- Add docstrings to all functions and methods in standalone scripts

---

## 5. Shell Scripts

- Use `#!/bin/bash` shebang
- Document shellcheck suppressions with comments
- Use color-coded output for pass/fail reporting
- Exit with appropriate codes (0 for success, 1 for failure)

---

## 6. Integration Tests for New Modules

Every new data collection module must be covered by the from-scratch
integration suite (`test/test_from_scratch.py`, run via
`test/run-test-from-scratch.sh`). See `data-collection/CONTRIBUTING.md` for how
to run it.

### 6.1 Enable the module in the deploy

Add the module's `Include<Module>Module: "yes"` parameter (and any required
module parameters) to `initial_deploy_stacks` in `test/utils.py`, next to the
other modules, so the from-scratch deploy exercises it.

### 6.2 Add a table assertion

Add a `test_<module>_data(athena)` function that queries the module's Athena
table and asserts it is non-empty — matching the existing table tests:

```python
def test_<module>_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."<table>" LIMIT 10;')
    assert len(data) > 0, '<table> is empty'
```

Keep the test itself a pure query. Do **not** put data-seeding or collection
triggering inside the test function — that belongs in the setup phase (6.3).

### 6.3 Ensure data exists before assertions (collection triggering)

The table tests rely on collection having already run during `prepare_stacks`
(via `trigger_update`, which launches the Step Functions and waits). A module
whose collection is **not** a Step Function launched by `trigger_update` (for
example, a scheduled Lambda that reads an external source) will find an empty
table unless collection is triggered explicitly. For those modules:

- Add a `trigger_<module>_collection(account_id)` helper in `test/utils.py` that
  seeds any required synthetic input and invokes the collector **synchronously**
  (`InvocationType='RequestResponse'`).
- Call it from `prepare_stacks` after `trigger_update`, so data is present by
  the time the assertion runs.
- Remember the from-scratch run empties `cid-data-<account_id>` at setup, so any
  seeded data must be (re)created during setup, not assumed to persist.

### 6.4 Do not hardcode account-specific values

Test inputs that vary by account (bucket names, source lists) must not be
committed as literals. Derive them from `account_id` and/or read an environment
variable with a convention-based default, e.g.:

```python
KIRO_SOURCE_BUCKETS = os.environ.get('KIRO_SOURCE_BUCKETS', f'cid-dc-kiro-activity-{account_id}')
```

Document any such environment variable in `data-collection/CONTRIBUTING.md`.
