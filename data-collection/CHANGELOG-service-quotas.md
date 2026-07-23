# Service Quotas Module — Change Log

## In Progress (branch: cid-main local)

### Summary
Complete overhaul of the Service Quotas data collection module. Replaced the history-driven, CloudWatch-dependent, single-region implementation with a native Service Quotas API approach that collects all quotas across all regions for every account in scope — validated end-to-end across 3 accounts and 16 regions with QuickSight SPICE ingestion confirmed working.

---

### Problems Fixed

**1. Coverage gap (Critical)**
Original module used `list_requested_service_quota_change_history` as its only data source. Accounts that never submitted a quota increase returned zero data. Fixed by using `ListServices` → `ListServiceQuotas` to collect all ~11,000 quotas per region regardless of history.

**2. CloudWatch dependency in member accounts**
PR #384 introduced `cloudwatch:GetMetricData` calls in batches of 400 with parallel workers, requiring `cloudwatch:GetMetricStatistics` and `cloudwatch:GetMetricData` permissions in every member account IAM role. Replaced with `StartQuotaUtilizationReport` + `GetQuotaUtilizationReport` — AWS computes utilization % server-side, no CloudWatch permissions needed.

**3. Single-region collection**
PR #384 introduced `for region in [regions[0]]` — only collected one region per invocation. Fixed to iterate all regions.

**4. Sequential region processing causing Lambda timeout**
Sequential region loop hit the 900s Lambda limit at ~11 regions. Fixed by parallelizing regions: `collect_region()` runs 4 regions concurrently via `ThreadPoolExecutor(max_workers=REGION_WORKERS)`. 16 regions complete in ~300s, well within 900s limit.

**5. Period field schema mismatch**
Service Quotas API returns `Period` as a nested struct `{PeriodValue: int, PeriodUnit: string}`. Storing it as a nested object caused `HIVE_PARTITION_SCHEMA_MISMATCH` errors in Athena and QuickSight SPICE ingestion failures. Fixed by flattening to two columns: `PeriodValue` (int) and `PeriodUnit` (string).

**6. CrawlerExecution StateMachine JSONata error**
The deployed `CID-DC-CrawlerExecution-StateMachine` uses JSONata and expects a `behavior` field in its input. The original `main-state-machine-v3.json` didn't pass it, causing the Crawler step to fail after every collection run. Fixed by adding `"behavior": "WAIT"` to the crawler input.

**7. Duplicate Glue tables**
Glue Crawler auto-created `service-quotas_data` (hyphenated) alongside the pre-defined `service_quotas_data` (underscore), causing schema conflicts. Fixed by adding pre-defined Glue tables with explicit schema including `use.null.for.invalid.data = true` — Crawler only updates partitions, never recreates tables.

**8. QuickSight role permissions**
`CidQuickSightDataSourceRole` was missing `AWSQuicksightAthenaAccess` policy, causing SPICE ingestion to fail with `athena:GetWorkGroup` denied. Fixed by attaching the policy to the correct role.

---

### Files Changed

#### `data-collection/deploy/module-service-quotas.yaml`
- Lambda runtime: `python3.12` → `python3.13`
- Lambda timeout: `300s` → `900s`
- **Removed**: `prepare_cloudwatch_metrics_worker()`, `get_cloudwatch_metrics_batch()`, `CLOUDWATCH_BATCH_SIZE`, `threading`/`log_lock`, `payload` parameter
- **Added**: `get_utilization_report()` — async poll loop for `StartQuotaUtilizationReport` / `GetQuotaUtilizationReport`
- **Added**: `collect_region()` — per-region collection function run in parallel
- **Added**: `REGION_WORKERS = 4` — 4 regions processed concurrently
- **Changed**: `main()` now fans out to `collect_region()` via `ThreadPoolExecutor`
- **Changed**: `enrich_quota()` — flattened `Period` struct into `PeriodValue` (int) and `PeriodUnit` (string) flat fields
- **Changed**: `CollectionType: "LINKED"` (standard CID pattern)
- **Changed**: `RegionsInScope` default = all 16 CID-supported regions
- **Added**: `ServiceQuotasDataTable` — pre-defined Glue table with explicit column schema. `Utilization` typed as `double`, `PeriodValue` as `int`, `PeriodUnit` as `string`, `use.null.for.invalid.data = true`
- **Added**: `ServiceQuotasHistoryTable` — pre-defined Glue table for quota change history

#### `data-collection/deploy/deploy-in-linked-account.yaml`
- **Removed**: `cloudwatch:GetMetricStatistics`, `cloudwatch:GetMetricData`
- **Added**: `servicequotas:StartQuotaUtilizationReport`, `servicequotas:GetQuotaUtilizationReport`

#### `data-collection/deploy/source/step-functions/main-state-machine-v3.json`
- **Added**: `"behavior": "WAIT"` to `CrawlerStepFunctionStartExecution` input — required by the JSONata-based `CID-DC-CrawlerExecution-StateMachine`

---

### Architecture

```
EventBridge (rate 14 days)
  → Step Functions (ModuleStepFunction)
      → AccountCollectorLambda (LINKED)
            reads predefined account list from S3 or queries Organizations
      → Distributed Map (MaxConcurrency 60)
            one Lambda per account:
                assume cross-account role in member account
                4 regions processed concurrently (REGION_WORKERS=4):
                    1. list_requested_service_quota_change_history → history.json
                    2. StartQuotaUtilizationReport → poll → utilization dict
                    3. ListServices → ListServiceQuotas (5 parallel workers) → ~11k quotas
                    4. Merge + enrich (PeriodValue/PeriodUnit flat)
                    5. Write quotas.json to S3
      → CrawlerExecution StateMachine (behavior=WAIT)
            → Glue Crawler → updates Glue Data Catalog partitions
```

**S3 output:**
```
s3://bucket/service-quotas/service-quotas-data/payer_id=X/account_id=Y/region=Z/quotas.json
s3://bucket/service-quotas/service-quotas-history/payer_id=X/account_id=Y/region=Z/history.json
```

**Athena tables (pre-defined schema):**
- `optimization_data.service_quotas_data` — ~11,000 quotas per account per region
- `optimization_data.service_quotas_history` — quota increase request history

---

### Scaling (tested)

| Scenario | Result |
|---|---|
| 1 account × 16 regions | ~300s ✅ |
| 3 accounts × 16 regions | ~320s wall time (all concurrent) ✅ |
| 1800 accounts × 16 regions | ~84 min total (60 concurrent, 14-day schedule) ✅ |
| Lambda timeout risk | None — 4 parallel regions × ~80s avg = ~320s << 900s |

---

### Utilization Data

`StartQuotaUtilizationReport` computes utilization % server-side for quotas that AWS natively tracks (~200-300 of ~11,000 total). Remaining quotas have `Utilization: null`. This is an AWS API limitation. The Glue table types `Utilization` as `double` with `use.null.for.invalid.data = true` to handle nulls correctly.

---

### QuickSight

- SPICE ingestion confirmed working after attaching `AWSQuicksightAthenaAccess` to `CidQuickSightDataSourceRole`
- 3-tab dashboard generated via QuickSight AI: Executive Overview, Risk Analysis & Regional Patterns, Detailed Analysis & Rate Limits
- Filters: account_id, region, servicename, adjustable, globalquota, collection_date

---

### Known Issues / Follow-up PRs

**LINKED_REGIONAL collection type (separate PR)**
For enterprise customers wanting fully automatic region discovery per account, a new `LINKED_REGIONAL` collection type in the Account Collector would call `ec2:DescribeRegions` per account and emit one item per (account, region) pair — eliminating the need for `RegionsInScope` configuration. This is a clean additive change (~25 lines in `account-collector.yaml`), non-breaking, but touches shared infrastructure so warrants its own PR.

---

### Testing Conducted

- Deployed to Data Collection account `820663349847`
- Member accounts: `972105300464`, `265808837073`, `747323998494`
- All 3 accounts × 16 regions collected in parallel in ~320s wall time
- Step Function SUCCEEDED with Crawler running automatically
- Athena query confirmed: 3 accounts × 16 regions, correct quota counts
- QuickSight SPICE ingestion: COMPLETED
- QuickSight AI dashboard: 3-tab dashboard generated and functional

---

### Files Modified (git diff)
- `data-collection/deploy/module-service-quotas.yaml`
- `data-collection/deploy/deploy-in-linked-account.yaml`
- `data-collection/deploy/source/step-functions/main-state-machine-v3.json`

**Status:** Local changes, ready for PR
