# Service Quotas Module — Change Log

## v1.0.0 — Native utilization API, parallel regions, service filter

Complete overhaul of the Service Quotas data collection module. Replaced the history-driven,
CloudWatch-dependent, single-region implementation with a native Service Quotas API approach
that collects all quotas across all regions for every account in scope.

### Problems Fixed

**1. Coverage gap**
Original module used `list_requested_service_quota_change_history` as its only data source.
Accounts that never submitted a quota increase returned zero data. Fixed by using
`ListServices` → `ListServiceQuotas` to collect all ~11,000 quotas per region regardless of history.

**2. CloudWatch dependency in member accounts**
PR #384 required `cloudwatch:GetMetricStatistics` and `cloudwatch:GetMetricData` permissions
in every member account IAM role. Replaced with `StartQuotaUtilizationReport` +
`GetQuotaUtilizationReport` — AWS computes utilization % server-side, no CloudWatch permissions needed.

**3. Single-region collection**
PR #384 introduced `for region in [regions[0]]` — only collected one region per invocation.
Fixed to iterate all configured regions.

**4. Lambda timeout on sequential region processing**
Sequential region loop exceeded the 900s Lambda limit at ~11 regions. Fixed by parallelizing
regions: `collect_region()` runs 4 regions concurrently via `ThreadPoolExecutor(max_workers=4)`.
16 regions complete in ~300s.

**5. Period field schema mismatch**
Service Quotas API returns `Period` as a nested struct `{PeriodValue: int, PeriodUnit: string}`.
Storing it as a nested object caused `HIVE_PARTITION_SCHEMA_MISMATCH` in Athena. Fixed by
flattening to two columns: `PeriodValue` (int) and `PeriodUnit` (string).

**6. Duplicate Glue tables**
Glue Crawler auto-created `service-quotas_data` (hyphenated) alongside the pre-defined
`service_quotas_data` (underscore), causing schema conflicts. Fixed by adding pre-defined
Glue tables with `UPDATED_BY_CRAWLER` binding and `use.null.for.invalid.data=true`.

### Files Changed

- `data-collection/deploy/module-service-quotas.yaml` — full Lambda rewrite, pre-defined Glue tables, service filter via payload
- `data-collection/deploy/deploy-in-linked-account.yaml` — replaced CloudWatch permissions with native Service Quotas API permissions
