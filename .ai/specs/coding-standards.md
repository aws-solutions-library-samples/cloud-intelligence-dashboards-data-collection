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
