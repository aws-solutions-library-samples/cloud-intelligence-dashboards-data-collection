---
inclusion: always unless expressly excluded
---

# Implementation Guide

How data collection modules run. For style and formatting rules see
[coding-standards.md](coding-standards.md); for where new data belongs and how to
wire a module see [data-collection/MODULE_GUIDELINES.md](../../data-collection/MODULE_GUIDELINES.md).

This guide covers the main state machine
(`data-collection/deploy/source/step-functions/main-state-machine.json`), which
most modules use. Modules on `standalone-state-machine.json` or their own state
machine (for example Health Events detail) differ; read their definition.

---

## Collection flow

```
EventBridge Scheduler (<prefix><module>-RefreshSchedule)
  → <prefix><module>-StateMachine (main-state-machine.json)
      → AccountCollectorLambda      writes the account list for this module to S3
      → DataCollectionMap           Distributed Map over that list, MaxConcurrency 60,
                                    ToleratedFailurePercentage 95
            → DataCollectionLambda  invokes <prefix><module>-Lambda once per account
      → CrawlerStepFunction         runs the module's crawlers
      → ExitLog
```

### Account list

The Account Collector (`account-collector.yaml`) builds the list from the payer
organizations, or from a list the customer provides:

- `account-list/account-list.*` replaces the organization lookup.
- `account-list/excluded-linked-account-list.csv` removes accounts.
- `account-list/granular-execution-config.csv` limits modules per account and
  can set regions and a payload per account.

By default **every account in scope is collected, for every LINKED module**,
including accounts where the customer never deployed or enabled the module.
Modules must handle that (coding-standards §2.7).

### Module Lambda input

Each map item invokes the module Lambda with:

```json
{
  "account": "{\"account_id\": \"...\", \"account_name\": \"...\", \"payer_id\": \"...\"}",
  "params": "<Params substitution from the module's state machine>",
  "main_exe_uuid": "...",
  "prefix": "<ResourcePrefix>",
  "stack_version": "..."
}
```

- `account` is a JSON **string**; parse it with `json.loads`. Records from the
  granular execution config can also include `regions` and `payload`.
- The Lambda must refuse to run without `account` (manual invocations), with the
  standard "Please do not trigger this Lambda manually" `ValueError`.
- For `CollectionType: LINKED` the Lambda assumes `${MultiAccountRoleName}` in
  `account_id`. For `Payers` it assumes `${ManagementRoleName}`; `account_id` is
  the payer, or a delegated administrator account when one is configured in SSM
  (`/cid/<prefix>config/delegated-admin/<service>/<payer_id>`). `EUC` modules get
  only the accounts listed in the `EUCAccountIDs` parameter.

### Output

The Lambda writes JSONL to `s3://<DestinationBucket>/<module>/<module>-<dataset>-data/...`
with the partition layout its table expects (Hive `payer_id=/year=/month=` with a
crawler, or date partitions with projection; coding-standards §1.8). The
crawler step registers new partitions after the map completes.

---

## Failure handling

| Event | What happens |
|---|---|
| Module Lambda raises, or times out | The map item goes `DCLambdaErrorMetric` → `DCLambdaErrorLog` → `FailMapLambda`. It puts an `Error` metric (namespace `CID-DataCollection`, dimension `Module`) and writes the error to `s3://<bucket>/logs/modules/YYYY/MM/DD/<module>-sf-error*.json`. Only `Lambda.TooManyRequestsException` is retried. |
| Up to 95% of map items fail | The map succeeds and the crawler runs. Failed accounts have no new data for this run. |
| More than 95% of map items fail | The map fails (`States.ExceedToleratedFailureThreshold`) → `ErrorMetric` → `ExitLog`. **The crawler does not run**, so partitions written by the accounts that succeeded are not registered either (unless the table uses partition projection). |
| Account Collector fails | `ErrorMetric` → `ExitLog`; nothing is collected. |

Consequences for module code:

- **Raising fails the account**, and many raising accounts fail the whole run.
  Raise only for real failures: data that could not be written, or nothing
  collected because of unexpected errors.
- **"Not deployed / not enabled / not available" is not a failure.** Customers
  enable a module in some accounts and regions only; skip and count those
  (coding-standards §2.7).
- **A timeout is a failure** and loses everything not yet uploaded. Stay inside
  the time budget (coding-standards §2.6).
- **Return a summary.** Return `{"statusCode": 200, "body": {...counts, "errors": [...]}}`;
  the map writes results to `s3://<bucket>/logs/mapruns/<module>/`, which is
  where partial failures and skipped accounts can be seen.
