---
inclusion: always unless expressly excluded
---

# Implementation Guide

Architecture and execution patterns for the CID data collection project.
For style rules and formatting, see coding-standards.md.

## Project Layout

```
data-collection/
├── deploy/                  # CloudFormation templates (production)
│   ├── deploy-data-collection.yaml   # Main nested stack
│   ├── module-*.yaml                 # One per data collection module
│   ├── deploy-in-*.yaml              # Account-level deployment templates
│   ├── source/
│   │   └── step-functions/           # Step Function JSON definitions
│   ├── data/                         # Static reference data (CSV)
│   └── layers/                       # Lambda layer artifacts
├── utils/                   # Build and release tooling
│   ├── release.sh           # S3 sync to central + regional buckets
│   ├── upload.sh            # Upload helper
│   ├── bump-release.py      # Version bumper
│   ├── version.json         # Current version
│   └── layer-utils/         # Lambda layer build scripts
└── sandbox/                 # Experimental / scratch work (gitignored)
```

## Module Pattern

Each data collection module follows a consistent structure:

1. A CloudFormation template (`module-<name>.yaml`) containing:
   - IAM role with least-privilege policies
   - Lambda function with inline Python (`ZipFile`)
   - CloudWatch log group (60-day retention)
   - Glue crawler for the collected data
   - Step Function state machine (references shared JSON definition)
   - EventBridge scheduler

2. The main stack (`deploy-data-collection.yaml`) includes each module as a nested stack, gated by an `Include*Module` parameter.

## Execution Flow

1. EventBridge scheduler triggers the module's Step Function
2. Step Function invokes the account collector Lambda to get target accounts
3. For each account, the module Lambda assumes a cross-account role
4. Lambda collects data via AWS APIs and writes JSONL to S3
5. Glue crawler updates the Athena table schema
6. Data is queryable in Athena under the `optimization_data` database

## Local Development Workflow

### Editing Lambda Code
1. Edit the Python file in `local-test/lambdas/module-<name>.py`
2. Test locally using `run_lambda_local.py`
3. Promote to CloudFormation using the "Promote Python Lambda" hook (or manually replace the ZipFile block with 10-space indentation)

### Lambda Layer Build
- `utils/layer-utils/boto3-layer-build.sh` builds a boto3 layer zip
- Output goes to `deploy/layers/boto3-layer.zip`
- Automatically run by `release.sh` before S3 sync

## Release Process

1. Bump version in `utils/version.json`
2. Run `utils/release.sh` which:
   - Builds the boto3 Lambda layer
   - Syncs `deploy/` to the central S3 bucket (latest + versioned)
   - Syncs to all regional buckets via StackSet

## Key Conventions

- Cross-account access uses STS AssumeRole with a configurable role name
- All modules write to a shared S3 bucket under `{prefix}/{prefix}-data/` paths
- Step Functions use JSONata query language for variable assignment
- Version string is embedded in Step Function definitions (`STACK_VERSION`)
- Boto3 retry config: adaptive mode with configurable `MAX_RETRIES` (default 10)
