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
- **Service-read permissions belong on the multi-account role, not the module's
  Lambda execution role.** For LINKED modules the collector Lambda runs in the
  data-collection account and *assumes* the multi-account role
  (`${MultiAccountRoleName}`) in each target account; the `describe_*` / `list_*`
  calls execute with the **assumed** role's credentials. Therefore:
  - The module template's `LambdaRole` (in `module-<svc>.yaml`) carries **only**
    plumbing: `sts:AssumeRole` on
    `arn:${AWS::Partition}:iam::*:role/${MultiAccountRoleName}`, `s3:PutObject` on
    `${DestinationBucketARN}/*`, and — when the bucket may be encrypted —
    `kms:GenerateDataKey`. It must **not** grant the service `describe_*` /
    `list_*` actions; those never run under this role, so granting them is dead
    (and often triggers an avoidable `W11` suppression).
  - The service-read actions (e.g. `rds:DescribePendingMaintenanceActions`) go in
    a least-privilege `AWS::IAM::Policy` on the multi-account role in
    `deploy-in-linked-account.yaml`, gated by the module's
    `Include<Name>ModulePolicy` condition.

  This is the established pattern — the execution role is plumbing-only
  (AssumeRole + S3 + KMS) across `module-inventory.yaml`, `module-rds-usage.yaml`,
  `module-budgets.yaml`, `module-transit-gateway.yaml`,
  `module-ecs-chargeback.yaml`, `module-support-cases.yaml`, and others; the
  service-read actions live in `deploy-in-linked-account.yaml`.

### 1.8 Glue Crawlers and Table Schemas

Data is written as JSONL and read by a Glue crawler into an Athena table.
Crawler type inference is **presence-dependent**: a field that is empty in one
partition and populated in another is inferred as different types, and those
partitions then fail to load together in the same Athena view (this has bitten
us before — e.g. `event_metadata` in the Health module). Rules:

- **Pre-create typed tables; don't let the crawler own the schema.** Declare the
  `AWS::Glue::Table` (or the inventory `AwsObjects` table mapping) with explicit
  columns and point the crawler at the same location so it only updates
  partitions.
- **Use the standard schema-safe crawler config on every crawler** so the crawler
  adds columns but never rewrites or drops existing ones:
  ```yaml
  Configuration: '{"Version":1.0,"Grouping":{"TableGroupingPolicy":"CombineCompatibleSchemas"},"CrawlerOutput":{"Partitions":{"AddOrUpdateBehavior":"InheritFromTable"},"Tables":{"TableThreshold":<n>,"AddOrUpdateBehavior":"MergeNewColumns"}}}'
  SchemaChangePolicy:
    UpdateBehavior: UPDATE_IN_DATABASE
    DeleteBehavior: LOG
  ```
  `TableThreshold` = the number of distinct S3 target paths that combine into one
  table (usually `1`). This config is standard across the modules — e.g.
  `module-trusted-advisor.yaml`, `module-inventory.yaml`, `module-health-events.yaml`,
  `module-identity-center.yaml`, `module-pricing.yaml`, and `module-resilience-hub.yaml`.
- **Prefer `string` (raw JSON) over `array<struct<…>>` or `map<…>` for variable
  or optional nested fields.** A `string` column never drifts and survives AWS
  API schema changes; parse it in a **derived Athena view** with `json_parse` /
  `json_extract` / `UNNEST` rather than baking a rigid shape into the table.
  Reserve `array<struct<…>>` / `map<string,string>` for stable shapes on a
  pre-created table with the crawler config above. Note `map<string,string>`
  requires flat string→string data *and* a pre-created table — crawlers infer a
  JSON object as `struct`, so they will overwrite a `map` column otherwise.
- **Crawler-free alternative: partition projection.** For date-partitioned data
  written in Hive layout (`year=YYYY/month=MM/day=DD/`), pre-create the table
  with `projection.enabled`, integer projections (`digits: '2'` for month/day),
  and a `storage.location.template`; pass `Crawlers: '[]'` to the Step Function.
  No crawler means no drift and no stale partitions. The date is the only
  partition: account and region, when a module writes per-account or
  per-region files, go in the file name —
  `<payer_id>[_<account_id>][_<region>]_YYYY_MM_DD.json`, built by
  `DcUtils.date_partitioned_key` — because CID queries filter on date. Columns follow the API
  response shape, and the Lambda conforms every record to the table before
  writing (`common.record_schema.RecordSchema`). Reference:
  `data-collection/samples/hello-dc/module-hello-dc.yaml`.

### 1.9 Template Versions in Nested-Stack URLs

Every nested-stack `TemplateURL` in `deploy-data-collection.yaml` (and the
version strings in the other `deploy-*.yaml` files) uses the version in
`data-collection/utils/version.json`, e.g.
`.../cfn/data-collection/v<version>/module-<name>.yaml`. `upload.sh` publishes
templates only to that path, so a stale version makes the stack update fail with
`NoSuchKey` and roll back.

- **Re-check after every merge from `main`.** A release bump on `main` rewrites
  all existing URLs, but the line your branch adds keeps its old version, and git
  merges it without a conflict. After merging `main`, all `TemplateURL`s must
  show the same version:
  ```bash
  grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+/' data-collection/deploy/deploy-data-collection.yaml | sort | uniq -c
  ```
- **Don't bump `version.json` in a feature PR.** Releases are separate PRs made
  with `data-collection/utils/bump-release.py`, which rewrites `v<old>` to
  `v<new>` across the `deploy-*.yaml` files, `main-state-machine.json`, and
  `version.json`. Keep version strings in those files only; module templates
  shouldn't contain the version.

### 1.10 Dependencies Between Modules

When a module depends on another module, for example by invoking another
module's Lambda or relying on permissions granted by another module's policy,
enforce it explicitly. A condition such as
`DeployXModule: !And [..., !Condition DeployYModule]` silently skips the module,
so the customer sets `IncludeXModule=yes` and nothing is deployed. Use a
`Rules:` assertion in `deploy-data-collection.yaml` instead, which fails the
deployment with a clear message:

```yaml
Rules:
  RDSModuleRequiresInventoryAndReference:
    RuleCondition: !Equals [!Ref IncludeRDSModule, "yes"]
    Assertions:
      - Assert: !Equals [!Ref IncludeInventoryCollectorModule, "yes"]
        AssertDescription: "IncludeRDSModule=yes requires IncludeInventoryCollectorModule=yes"
```

- State the requirement in the `Include<Name>Module` parameter description as
  well ("Requires the Inventory and Reference modules").
- Require only modules the collection or its primary dashboard can't work
  without. Don't require the Org Data module for account names: dashboards get
  them from the `account_map` view, which `cid-cmd` can build without Org Data.
- Check dependencies when enabling resources that were previously disabled (for
  example, a schedule changing from `DISABLED` to `ENABLED`). A disabled
  schedule hides a missing dependency; an enabled one fails on every run.

### 1.11 Changing Existing Tables Safely (Upgrades)

Customers upgrade in place, so schema and crawler changes run against existing
partitions:

- **Changing a column's type** (for example `array<…>` to `string`) makes
  Athena fail with `HIVE_PARTITION_SCHEMA_MISMATCH` until the crawler re-crawls
  the old partitions. With the standard config (`InheritFromTable`), one crawl
  fixes it, so queries break only until the next scheduled collection. Call this
  out in the release notes; dashboards that refresh SPICE in that window fail
  their refresh once.
- **Changing a crawler's `Configuration`** fails the stack update with
  `Cannot update Crawler while running` if that crawler is running, and the
  stack rolls back. Avoid touching crawlers you don't need to change, and
  mention it in the release notes for changes that touch many crawlers.
- Test the upgrade path, not only a fresh install (§6.6).

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

### 2.5 Common Lambda Layer

- Source of truth: `data-collection/deploy/source/common/` (versioned by
  `__version__` in `__init__.py`). `local-test/lambdas/common` is a symlink to it.
- Build with `data-collection/utils/layer-utils/common-layer-build.sh` →
  `data-collection/deploy/layers/common-layer.zip` (gitignored; uploaded by `upload.sh`).
- Modules subclass `common.module.DataCollectionModule`, declare `MODULE` and
  `COLLECTORS`, and override hooks rather than copying superclass code:
  `session_for` (credentials), `output_key` (S3 layout), `conform` (record shape).
- Starting point for a new module: `data-collection/samples/hello-dc/`.

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
- **Paginate every AWS `list_*` / `describe_*` call** with
  `client.get_paginator(...)` (or an explicit token loop). Never read a single
  response page: APIs such as `describe_pending_maintenance_actions` cap results
  per page and silently truncate collection for large accounts.
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

### 6.5 Assertions must be able to fail

Assert that each new table returns rows (`len(data) > 0`). An assertion such as
`len(data) >= 0` always passes and only proves the query compiled. If a table
can legitimately be empty (for example, pending maintenance actions), say so in
the test name or docstring and assert something that can fail, such as that the
table exists with the expected columns.

### 6.6 Test the upgrade path for changes to existing modules

`run-test-from-scratch.sh` covers a fresh install. When a change modifies
existing tables, crawlers, or wiring, also test an in-place upgrade:

1. Deploy from `main` and let collection run, so the tables have partitions.
2. Update the same stacks with the branch templates (`upload.sh`, then
   `update-stack` with `UsePreviousValue` for existing parameters). Don't use
   the from-scratch harness for this step, because `prepare_stacks` empties the
   data bucket.
3. Check that the stack update completes, then query the changed tables before
   and after the next crawl.

---

## 7. Review Checklist for Module Changes

Fast checks when authoring or reviewing a data-collection module (each links to
the section with detail):

- [ ] **Permission placement** — execution-role holds only `AssumeRole` +
      `s3:PutObject` + KMS; service `describe_*` / `list_*` permissions live on
      the multi-account role in `deploy-in-linked-account.yaml`, gated by
      `Include<Name>ModulePolicy` (§1.7).
- [ ] **Pagination** — every `list_*` / `describe_*` call is paginated (§4).
- [ ] **Crawlers & schemas** — every crawler uses the standard schema-safe config
      (`InheritFromTable` / `MergeNewColumns` + `SchemaChangePolicy`) and points at
      a pre-created table; variable nested fields are `string` + Athena view, not
      `array<struct<…>>` / `map` (§1.8).
- [ ] **Analytics** — `AnalyticsExecutor` (`Custom::LambdaAnalyticsExecutor`)
      resource is present and wired to `LambdaAnalyticsARN`.
- [ ] **KMS** — a `kms:GenerateDataKey` policy exists whenever the module accepts
      `DataBucketsKmsKeysArns`.
- [ ] **Naming** — the same token appears in the file name, `Include…Module`
      parameter, `Deploy…` condition, and nested-stack logical id
      (`data-collection/MODULE_GUIDELINES.md` §3).
- [ ] **Topology** — LINKED-only modules do **not** modify
      `deploy-in-management-account.yaml`; payer-account coverage comes from
      deploying `deploy-in-linked-account.yaml` into the management account
      (MODULE_GUIDELINES §5).
- [ ] **Wiring completeness** — the `Include…Module` parameter is threaded
      through every consumer in `deploy-data-read-permissions.yaml` (org StackSet
      **and** the management-account nested stack).
- [ ] **Tests** — the module is enabled in the from-scratch suite with a table
      assertion that can fail (§6, §6.5).
- [ ] **Template version** — the new `TemplateURL` uses the version in
      `version.json` (re-check after every merge from `main`); `version.json`
      itself is not bumped (§1.9).
- [ ] **Module dependencies** — dependencies on other modules are enforced with
      a `Rules:` assertion and stated in the parameter description, not by a
      condition that silently skips the module (§1.10).
- [ ] **Upgrade safety** — changes to existing column types or crawler
      configuration are called out in the release notes, and the in-place
      upgrade was tested (§1.11, §6.6).
