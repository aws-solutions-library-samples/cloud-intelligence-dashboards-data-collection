# Service Quotas Data Collection Module

## Overview

The Service Quotas module collects AWS Service Quota data across all accounts and regions in your AWS Organization. It uses the native Service Quotas API to gather quota limits, default values, and utilization percentages — enabling teams to proactively identify and address quota constraints before they impact workloads.

**Schedule:** Every 14 days (configurable)
**Collection scope:** All accounts in scope × all configured regions
**Output:** Two Athena tables in `optimization_data` database

---

## Why This Module Uses Threading

This is the only CID data collection module that uses Python `ThreadPoolExecutor` for parallel processing. Here's why.

Every other module makes a small number of API calls per region:

| Module | API calls per region | Timeout risk |
|---|---|---|
| Trusted Advisor | ~1 (list recommendations) | None |
| Inventory | ~5-10 (describe instances, volumes, etc.) | None |
| RDS Usage | ~3-5 (describe instances + CW metrics) | None |
| Transit Gateway | ~1 (describe attachments) | None |
| **Service Quotas** | **~313 (one `ListServiceQuotas` per service)** | **High without threading** |

Service Quotas must call `ListServiceQuotas` once per AWS service to collect all quota data. With 313 services per region, a sequential loop would take ~150s per region. For 16 regions:

```
Sequential (before):  16 × 150s = 2,400s  ❌ exceeds 900s Lambda limit
4 parallel (after):   4 waves × 150s = 600s... 
                      but regions themselves are I/O-bound so 4 concurrent ≈ 80s per wave
                      4 waves × 80s = ~320s  ✅ well within 900s
```

**Two levels of parallelism:**

```
Level 1 — Step Functions (account level)
  → one Lambda per account, 60 running simultaneously
  → handled by the CID framework, same as all other modules

Level 2 — ThreadPoolExecutor (region level, inside each Lambda)
  → 4 regions processed concurrently within a single Lambda invocation
  → unique to this module because of the high API call volume per region
```

The threads are I/O-bound (waiting for API responses) so Python's GIL is not a bottleneck — threads genuinely run in parallel while waiting for network responses.

---

## How It Works

```
EventBridge (rate 14 days)
  → Step Functions
      → Account Collector — reads account list from S3 or AWS Organizations
      → Distributed Map (60 concurrent) — one Lambda per account
            → Assumes cross-account role in member account
            → 4 regions processed in parallel per Lambda invocation
            → Writes quota data to S3
      → Glue Crawler — updates Athena table partitions
```

Each Lambda invocation for a single account processes all configured regions in groups of 4 concurrently, completing ~16 regions in approximately 300 seconds — well within the 900s Lambda timeout.

---

## Deployment

### Prerequisites
- `deploy-in-management-account.yaml` deployed in the Management/Payer account
- `deploy-in-linked-account.yaml` deployed in each member account with `IncludeServiceQuotasModule=yes`
- Data Collection account with the main `deploy-data-collection.yaml` stack

### S3 Bucket Layout

```
s3://{DestinationBucket}/
│
├── account-list/                             ← Account Collector reads these (optional)
│   ├── account-list.csv                      ← Predefined account list (skips Organizations)
│   │     format: account_id,account_name,payer_id
│   └── granular-execution-config.csv         ← Per-account rules (highest priority)
│         format: account_id,regions,payload
│         payload: colon-separated service codes, e.g. "ec2:s3:lambda"
│                  empty or "*" = collect all services (default)
│
└── service-quotas/                           ← Lambda writes here after collection
    ├── service-quotas-data/                  ← Full quota inventory
    │   └── payer_id={X}/
    │       └── account_id={Y}/
    │           └── region={Z}/
    │               └── quotas.json           ← JSONL, one record per quota
    │
    └── service-quotas-history/               ← Quota increase request history
        └── payer_id={X}/
            └── account_id={Y}/
                └── region={Z}/
                    └── history.json          ← JSONL, one record per increase request
```

The `payer_id`, `account_id`, and `region` path segments become **Athena partition keys** — the Glue Crawler picks them up automatically and makes them filterable columns in queries.

### Parameters

| Parameter | Description | Default |
|---|---|---|
| `RegionsInScope` | Comma-separated list of AWS regions to collect from | All 16 CID-supported regions |
| `Schedule` | EventBridge schedule expression | `rate(14 days)` |
| `DatabaseName` | Athena database name | `optimization_data` |
| `MultiAccountRoleName` | Cross-account IAM role name in member accounts | `Optimization-Data-Multi-Account-Role` |

### IAM Permissions Required in Member Accounts
The following permissions must be granted in the cross-account role (`deploy-in-linked-account.yaml`):
- `servicequotas:ListServices`
- `servicequotas:ListServiceQuotas`
- `servicequotas:ListAWSDefaultServiceQuotas`
- `servicequotas:ListRequestedServiceQuotaChangeHistory`
- `servicequotas:StartQuotaUtilizationReport`
- `servicequotas:GetQuotaUtilizationReport`

---

## Athena Tables

### `optimization_data.service_quotas_data`
Full quota inventory collected every 14 days. One record per quota per account per region.

#### Columns

**Identity**

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `servicecode` | string | AWS service identifier (e.g. `ec2`, `s3`, `lambda`) | Join with history table, filter by service |
| `servicename` | string | Human-readable service name (e.g. `Amazon EC2`) | Display in dashboards |
| `quotacode` | string | Unique quota identifier within a service (e.g. `L-1216C47A`) | Uniquely identify a quota |
| `quotaname` | string | Human-readable quota name (e.g. `Running On-Demand Standard instances`) | Display in dashboards |

**Limits**

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `currentvalue` | double | The applied quota value currently enforced in the account | The limit you are working against |
| `defaultvalue` | double | The AWS default for this quota before any increases | Compare to currentvalue to see if an increase was already requested |
| `appliedvalue` | double | Applied value sourced from the utilization report. Present only when utilization data exists | Cross-reference with currentvalue |
| `unit` | string | Unit of measurement (e.g. `None`, `Megabytes`, `Requests`) | Context for interpreting the value |

**Utilization**

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `utilization` | double | Current usage as % of the applied limit (0–100+). Only populated for quotas AWS natively tracks | The most actionable field — how close you are to the limit |
| `namespace` | string | CloudWatch namespace used to track usage (e.g. `AWS/EC2`) | Identifies the source of utilization data |

**Behavior**

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `adjustable` | boolean | Can you request an increase for this quota? | Filter to actionable quotas — only adjustable ones can be increased |
| `globalquota` | boolean | Does this quota apply account-wide or per-region? | IAM users is global; EC2 vCPUs is regional |
| `quotaappliedatlevel` | string | Whether quota is applied at `ACCOUNT` or `RESOURCE` level | Resource-level quotas apply per individual resource (e.g. per OpenSearch domain) |
| `quotaarn` | string | Amazon Resource Name for this quota | Direct link to the quota in the AWS console |

**Rate Limits** (only populated for rate-based quotas)

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `periodvalue` | int | The number part of the rate window (e.g. `1`, `100`) | Combined with periodunit: defines the rate window |
| `periodunit` | string | The unit of the rate window (`SECOND`, `MINUTE`, `DAY`) | e.g. `periodvalue=100, periodunit=SECOND` means "100 requests per second" |

**Metadata**

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `collection_date` | string | Timestamp when this record was collected | Track changes over time, identify stale data |

**Partitions** (inferred from S3 path)

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `payer_id` | string | Management/payer account ID | Multi-org support, billing consolidation |
| `account_id` | string | Member account ID where quotas were collected | Filter by account |
| `region` | string | AWS region where quotas were collected | Filter by region |

---

### `optimization_data.service_quotas_history`
Quota increase request history. Updated every 14 days. Covers the last 90 days of requests per the AWS API.

#### Columns

| Column | Type | Definition | Purpose |
|---|---|---|---|
| `id` | string | Unique request ID | Identify a specific increase request |
| `caseid` | string | Associated AWS Support case ID | Track support case for the request |
| `servicecode` | string | AWS service identifier | Join with quotas_data |
| `servicename` | string | Human-readable service name | Display |
| `quotacode` | string | Quota identifier | Join with quotas_data |
| `quotaname` | string | Human-readable quota name | Display |
| `desiredvalue` | double | The value the customer requested | What was asked for |
| `status` | string | Request status: `PENDING`, `APPROVED`, `DENIED`, `CASEOPENED`, `CASECLOSED`, `NOTAPPROVED` | Track request outcomes |
| `created` | string | When the request was submitted | Audit trail |
| `lastupdated` | string | When the request was last updated | Track progress |
| `quotaarn` | string | ARN of the quota | Direct link to quota |
| `quotarequestedatlevel` | string | `ACCOUNT` or `RESOURCE` | Level at which increase was requested |
| `requester` | string | IAM identity that submitted the request | Audit trail — who requested it |
| `requesttype` | string | `AutomaticManagement` if auto-requested by Service Quotas, otherwise empty | Distinguish manual vs automated requests |
| `globalquota` | boolean | Whether the quota is global | Context |
| `unit` | string | Unit of measurement | Context |
| `quotacontext` | string | Resource ARN for resource-level quota requests | Which specific resource the request applies to |
| `collection_date` | string | When this record was collected | Track collection runs |
| `payer_id` | string | Payer account ID (partition) | Multi-org |
| `account_id` | string | Member account ID (partition) | Filter by account |
| `region` | string | AWS region (partition) | Filter by region |

---

## Example Queries

**Top 20 quotas by utilization:**
```sql
SELECT account_id, region, servicename, quotaname, 
       currentvalue, appliedvalue, utilization
FROM optimization_data.service_quotas_data
WHERE utilization IS NOT NULL
ORDER BY utilization DESC
LIMIT 20
```

**Quotas at risk (above 80% utilization) that can be increased:**
```sql
SELECT account_id, region, servicename, quotaname,
       currentvalue, utilization, adjustable
FROM optimization_data.service_quotas_data
WHERE utilization > 80
  AND adjustable = true
ORDER BY utilization DESC
```

**Accounts with quota increase history in the last 90 days:**
```sql
SELECT account_id, servicename, quotaname, 
       desiredvalue, status, created, requester
FROM optimization_data.service_quotas_history
ORDER BY created DESC
```

**Quotas that have been increased above default:**
```sql
SELECT account_id, region, servicename, quotaname,
       defaultvalue, currentvalue,
       (currentvalue - defaultvalue) as increase_amount
FROM optimization_data.service_quotas_data
WHERE currentvalue > defaultvalue
ORDER BY increase_amount DESC
```

**Rate-limited quotas:**
```sql
SELECT account_id, region, servicename, quotaname,
       currentvalue, periodvalue, periodunit, utilization
FROM optimization_data.service_quotas_data
WHERE periodvalue IS NOT NULL
ORDER BY utilization DESC NULLS LAST
```

---

## Known Constraints

**Utilization data coverage:** `StartQuotaUtilizationReport` returns utilization % only for quotas AWS natively tracks via CloudWatch (~200-300 of ~11,000 total quotas). The remaining quotas have `Utilization: null`. This is an AWS API limitation — not a gap in the module.

**Region scaling:** With `REGION_WORKERS=4` and ~80s per region average, 16 regions complete in ~300s per account. The 900s Lambda timeout supports up to ~11 regions sequentially or ~16 regions in parallel groups of 4. Customers with significantly more than 16 regions should consider the `LINKED_REGIONAL` Account Collector enhancement (see Future Work below).

---

## Future Work

**LINKED_REGIONAL collection type**
A follow-up PR to add a `LINKED_REGIONAL` collection type to the Account Collector that automatically calls `ec2:DescribeRegions` per member account and emits one collection item per (account, region) pair. This eliminates the need for `RegionsInScope` configuration — every account's enabled regions are discovered automatically. Non-breaking additive change to `account-collector.yaml`.
