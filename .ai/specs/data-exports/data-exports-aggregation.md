# Data Exports Aggregation Template Specification

Template: `data-exports/deploy/data-exports-aggregation.yaml`
Version: v0.11.1 (AWS Solution SO9011)

## Overview

A single CloudFormation template deployed in both **source** and **destination** accounts to manage AWS Billing Data Exports (CUR 2.0, FOCUS, Cost Optimization Hub, Carbon Emissions). Data Exports are created in source accounts and delivered directly to the destination account's S3 bucket using the `S3BucketOwner` property.

## Supported Data Export Types

| Export | Table Name | CFN Map Key | Parameter |
|--------|-----------|-------------|-----------|
| CUR 2.0 | `cur2` | `CUR2` | `ManageCUR2` |
| FOCUS 1.2 | `focus` | `FOCUS` | `ManageFOCUS` |
| Cost Optimization Hub | `coh` | `COH` | `ManageCOH` |
| Carbon Emissions | `carbon` | `Carbon` | `ManageCarbon` |

## Account Roles

The template determines its role based on `DestinationAccountId` vs `AWS::AccountId`:

### Destination Account (`IsDestinationAccount`)

Resources created:
- **DestinationS3** — S3 bucket `{prefix}-{accountId}-data-exports` receiving data from all source accounts
- **DestinationS3BucketPolicy** — Grants `bcm-data-exports.amazonaws.com` write access, scoped by `aws:SourceAccount`
- **Glue Database** — `{prefix}_data_export` (hyphens replaced with underscores)
- **Glue Tables** — One per enabled export type (cur2, focus, coh, carbon)
- **Glue Crawlers** — One per table, scheduled daily at 2 AM UTC
- **DataExportsReadAccess** — IAM managed policy for QuickSight read access
- **Write Blocker** (optional) — Lambda + EventBridge rules to temporarily disable writes during QuickSight refresh

### Source Account (`IsSourceAccount`)

Resources created:
- **Data Exports** — One per enabled export type, created via:
  - Native CFN (`AWS::BCMDataExports::Export`) in us-east-1, cn-northwest-1, us-iso-east-1, us-iso-west-1
  - Custom Resource Lambda (`CidDataExportCreatorLambda`) in all other regions
  - **Bucket Policy Dependency**: CFN-based exports use a conditional implicit dependency on `DestinationS3BucketPolicy` via `Metadata` to prevent a race condition in same-account deployments (see [Bucket Policy Race Condition](#bucket-policy-race-condition) below)
- **SourceS3** (conditional) — Legacy local bucket `{prefix}-{accountId}-data-local`, created when `LegacyLocalBucket=yes` or `SecondaryDestinationBucket` is non-empty
- **ReplicationRole** (conditional) — IAM role for S3 replication, created only when `SecondaryDestinationBucket` is non-empty
- **COH Service Linked Role** (conditional) — Created via custom resource when COH export is enabled

## Data Delivery Model

### Current: Direct Delivery via S3BucketOwner

Data Exports write directly to the destination bucket using the `S3BucketOwner` property:
```
Source Account Data Export → s3://{prefix}-{destAccountId}-data-exports/{type}/{sourceAccountId}/{prefix}-{type}/data/
```

### Legacy: S3 Replication (deprecated)

Previously, Data Exports wrote to a local bucket in the source account, which replicated to the destination. This is retained for backward compatibility during the transition period.

### Secondary Destination Replication

When `SecondaryDestinationBucket` is provided:
- `SourceS3` is created with versioning enabled
- Replication rules replicate the `data/` prefix for each enabled export to the secondary bucket
- Only the `data/` folder is replicated (not `metadata/`)

## S3 Path Structure

```
s3://{prefix}-{destAccountId}-data-exports/
  ├── cur2/{sourceAccountId}/{prefix}-cur2/
  │   ├── data/BILLING_PERIOD=YYYY-MM/*.parquet
  │   └── metadata/BILLING_PERIOD=YYYY-MM/*-Manifest.json
  ├── focus/{sourceAccountId}/{prefix}-focus/
  │   ├── data/...
  │   └── metadata/...
  ├── coh/{sourceAccountId}/{prefix}-coh/
  │   ├── data/...
  │   └── metadata/...
  └── carbon/{sourceAccountId}/{prefix}-carbon/
      ├── data/...
      └── metadata/...
```

## Glue Crawler Configuration

All crawlers share these settings:
- Schedule: `cron(0 2 * * ? *)` (daily at 2 AM UTC)
- Schema change policy: `DeleteBehavior: LOG`
- Recrawl policy: `CRAWL_EVERYTHING`
- Table grouping: `CombineCompatibleSchemas`
- Column behavior: `MergeNewColumns`

### Exclusions

Each crawler excludes:
- `**.json`, `**.yml`, `**.sql`, `**.csv`, `**.csv.metadata`, `**.gz`, `**.zip`
- `**/cost_and_usage_data_status/*`
- `**/metadata/**` — Prevents Athena errors from manifest JSON files being parsed as Parquet
- `aws-programmatic-access-test-object`

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DestinationAccountId` | (required) | Account ID where data is delivered |
| `ResourcePrefix` | `cid` | Prefix for all resource names |
| `ManageCUR2/FOCUS/COH/Carbon` | `no` | Enable each export type |
| `SourceAccountIds` | `''` | Comma-separated source account IDs (destination only) |
| `EnableSCAD` | `yes` | Include Split Cost Allocation Data in CUR 2.0 |
| `LegacyLocalBucket` | `yes` | Retain local S3 bucket for backward compatibility |
| `SecondaryDestinationBucket` | `''` | Optional bucket for secondary data replication |
| `LakeFormationEnabled` | `no` | Enable Lake Formation tag associations |
| `AddScheduleForBlockingWrite` | `no` | Enable scheduled write blocking for QuickSight refresh |


## Deployment Scenarios

### Scenario 1: New Deployment (Single Account)

Source and destination are the same account.

**Parameters:**
- `DestinationAccountId` = own account ID
- `SourceAccountIds` = own account ID (first in list)
- `LegacyLocalBucket` = `no`
- Enable desired exports

**Result:**
- Destination bucket created with Data Exports write policy
- Data Exports created, writing directly to destination bucket
- Glue database, tables, and crawlers created
- No local bucket, no replication

### Scenario 2: New Deployment (Multi-Account)

Separate source and destination accounts.

**Destination account deployment:**
- `DestinationAccountId` = own account ID
- `SourceAccountIds` = comma-separated list of source account IDs
- `LegacyLocalBucket` = `no`

**Each source account deployment:**
- `DestinationAccountId` = destination account ID
- `LegacyLocalBucket` = `no`
- Enable desired exports

**Result:**
- Destination: bucket, policy, Glue resources
- Source: Data Exports writing directly to destination bucket via `S3BucketOwner`
- No local buckets or replication in any account

### Scenario 3: Update from Legacy (Replication-based) to Direct Delivery

Existing stacks used S3 replication from local bucket to destination.

**Step 1 — Update destination stack first:**
- `LegacyLocalBucket` remains `yes` (default, preserved from previous deployment)
- Destination bucket policy now includes both:
  - New: `bcm-data-exports.amazonaws.com` service principal for direct writes
  - Legacy: Replication write/read permissions (retained while `LegacyLocalBucket=yes`)

**Step 2 — Update source stacks:**
- Data Exports are recreated with `S3BucketOwner` pointing to destination
- Data Exports now write directly to destination bucket
- Local bucket retained (with `LegacyLocalBucket=yes`) but no longer receives new data
- Old replication configuration removed (unless `SecondaryDestinationBucket` is set)

**Step 3 — Cleanup (optional, after verifying data flows correctly):**
- Empty the local bucket in each source account
- Update source stacks with `LegacyLocalBucket=no`
- Update destination stack with `LegacyLocalBucket=no` to remove legacy replication policy statements

**Transition window:** Between Step 1 and Step 2, source stacks may still replicate data to the destination. The legacy replication policy on the destination bucket ensures this continues to work.

### Scenario 4: Deployment with Secondary Destination Bucket

Customer wants data replicated to an additional bucket.

**Source account deployment:**
- `SecondaryDestinationBucket` = target bucket name
- Enable desired exports

**Result:**
- Local bucket created with versioning enabled
- Data Exports write to local bucket
- Replication rules replicate `data/` folders to secondary bucket (one rule per export type)
- Replication role created with permissions scoped to secondary bucket only
- Each replication rule is enabled/disabled based on corresponding export toggle

### Scenario 5: Removing Secondary Destination Bucket

Customer no longer needs secondary replication.

- Set `SecondaryDestinationBucket` = `''` (empty)
- If `LegacyLocalBucket=no`, the local bucket condition (`DeploySourceS3`) becomes false
- CloudFormation will attempt to remove the local bucket (retained via `DeletionPolicy: Retain`)
- Replication role is removed

## Backward Compatibility

### LegacyLocalBucket Parameter

- Default: `yes` — ensures existing stacks retain the local bucket on update
- New deployments set `no` via deployment link
- CloudFormation preserves parameter values across updates, so once set to `no`, it stays `no`
- Controls:
  - `DeploySourceS3` condition (along with `NonEmptySecondaryDestinationBucket`)
  - Legacy replication policy statements on destination bucket

### Destination Bucket Policy Transition

When `LegacyLocalBucket=yes`, the destination bucket policy includes:
1. `EnableAWSDataExportsToWriteToS3` — for direct Data Export delivery (always present)
2. `AllowReplicationWrite` — legacy replication write permissions (conditional)
3. `AllowReplicationRead` — legacy replication read/versioning permissions (conditional)

When `LegacyLocalBucket=no`, only statement 1 is included.

### SourceS3 Bucket Retention

- Changed from `DeletionPolicy: Delete` to `DeletionPolicy: Retain`
- Prevents CloudFormation from failing when trying to delete a non-empty bucket during update
- Customers must manually empty and delete the bucket after migration

### Bucket Policy Race Condition

In same-account deployments (`IsSourceAccount` and `IsDestinationAccount` both true), CloudFormation creates the Data Export resources and the `DestinationS3BucketPolicy` in parallel. The BCM Data Exports service validates S3 write permissions at export creation time, so if the bucket policy hasn't been applied yet, the export fails with `S3 bucket permission validation failed`.

**Problem constraints:**
- `DependsOn` cannot be used because the export conditions (`Deploy{Type}ViaCFN` = `IsSourceAccount + ...`) don't imply `IsDestinationAccount`. In source-only deployments, `DestinationS3BucketPolicy` doesn't exist, and `DependsOn` on a non-existent conditional resource causes `Template format error: Unresolved resource dependencies`.
- CloudFormation's `DependsOn` attribute does not support `Fn::If` — it must be a string or list of strings.

**Solution:** Each CFN-based export resource includes a conditional implicit dependency in its `Metadata`:
```yaml
Metadata:
  BucketPolicyDependency: !If [IsDestinationAccount, !Ref DestinationS3BucketPolicy, '']
```

- In same-account deployments (`IsDestinationAccount` = true): `!Ref DestinationS3BucketPolicy` creates an implicit dependency, so CloudFormation waits for the bucket policy before creating the export.
- In source-only deployments (`IsDestinationAccount` = false): evaluates to `''`, no dependency created, no error.

This pattern is based on the CloudFormation technique of using `Metadata` with `Fn::If` to create conditional implicit dependencies without requiring `DependsOn`.

## Conditions Reference

| Condition | Logic |
|-----------|-------|
| `IsDestinationAccount` | `DestinationAccountId == AWS::AccountId` |
| `IsSourceAccount` | Not destination, OR destination listed first in SourceAccountIds |
| `LegacyLocalBucket` | `LegacyLocalBucket == 'yes'` |
| `NonEmptySecondaryDestinationBucket` | `SecondaryDestinationBucket != ''` |
| `DeploySourceS3` | Source + any export + (legacy OR secondary bucket) |
| `DeploySecondaryReplication` | Source + any export + secondary bucket |
| `DeployDataExport` | Any of CUR2/FOCUS/COH/Carbon enabled |
| `RegionSupportsDataExportsViaCFN` | us-east-1, cn-northwest-1, us-iso-east-1, us-iso-west-1 |
| `Deploy{Type}ViaCFN` | Source + type enabled + region supports CFN |
| `Deploy{Type}ViaLambda` | Source + type enabled + region does NOT support CFN |
| `Deploy{Type}Table` | Destination + type enabled |
| `DeployWriteBlocker` | Destination + `AddScheduleForBlockingWrite=yes` |
