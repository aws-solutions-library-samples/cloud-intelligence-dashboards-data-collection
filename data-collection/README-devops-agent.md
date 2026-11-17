# AWS DevOps Agent Data Collection Module

## Overview

The DevOps Agent module collects operational data from [AWS DevOps Agent](https://aws.amazon.com/devops-agent/) across all accounts and regions in your AWS Organization: Agent Spaces, backlog tasks (investigations, evaluations, system learning, custom agents), their executions, the full **journal records** written by the agent while it works, every tool call it made, and the monthly usage hours per account.

The result is a queryable audit trail of what the agent did, in which account and Agent Space, with which tools, and at what cost in tokens and hours. It feeds the **AWS DevOps Agent Dashboard** in the [CID framework](https://github.com/aws-solutions-library-samples/cloud-intelligence-dashboards-framework) (`dashboards/devops-agent/`).

**Schedule:** Daily (`ScheduleFrequent`, configurable)
**Collection scope:** All accounts in scope × regions in `RegionsInScope`
**Output:** Five Athena tables in the `optimization_data` database

---

## How It Works

```
EventBridge Scheduler (rate 1 day)
  → Step Functions (main-state-machine, CollectionType=LINKED)
      → Account Collector — reads account list from S3 or AWS Organizations
      → Distributed Map — one Lambda per account
            → Assumes the cross-account role in the member account
            → For each region in RegionsInScope:
                GetAccountUsage          → account-usage
                ListAgentSpaces          → agent-spaces
                ListBacklogTasks         → tasks created in the last TaskLookbackDays
                ListExecutions           → per task, joined with the task row
                ListJournalRecords       → per execution that is running or was updated
                                           in the last JournalLookbackDays
                                         → journal-records + tool-usage
            → Writes JSONL files to S3
      → Glue Crawler — registers new partitions
```

Tasks are processed in parallel inside the Lambda (`ThreadPoolExecutor`, 8 workers) because one `ListJournalRecords` page holds at most 100 records and a long investigation can have several thousand. The Lambda stops starting new work 90 s before its 900 s timeout and defers the rest to the next run; nothing is lost because the next run re-collects anything still inside the lookback windows.

### Incremental collection

The module is stateless. Each run collects:

- every task created within `TaskLookbackDays` (default 14), so status changes after creation are captured by re-collection;
- journal records only for executions that are still running or were updated within `JournalLookbackDays` (default 3). Finished executions older than that were already captured by an earlier run.

Because the same task or record can be written more than once, the dashboard views keep the latest snapshot per key with `ROW_NUMBER() OVER (PARTITION BY <key> ORDER BY collection_time DESC)`. Query the views, not the raw tables, unless you want the collection history.

### How journal records are stored

A journal record is `{recordId, recordType, createdAt, userReference, content}`. The `content` field is free-form JSON that differs for each `record_type` (`message`, `usage_metrics`, `utilization`, `task_summary`, …). The module keeps `content` **verbatim as a string** so nothing is lost, and promotes a small set of fields to typed columns:

| `record_type` | Promoted columns |
|---|---|
| `message` / `agent_message` | `message_role`, `text_preview`, `tool_use_count`, `tool_error_count`, `tool_names` |
| `usage_metrics` | `agent_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cache_*_tokens`, `duration_seconds`, tool call counts |
| `utilization` | `context_window_utilization`, `tool_names` (names only, counts would double-count) |
| anything else | `text_preview` from the first text-like field |

**Tool usage** rows are derived from the same records. A `toolUse` block in an assistant `message` (record *N*) is matched to its `toolResult` block in the following user `message` (record *N+1*) by `toolUseId`, which gives each tool call a `status` (`success` / `error`). `usage_metrics` records also contribute per-tool call counts.

---

## Deployment

### Prerequisites
- `deploy-in-management-account.yaml` deployed in the Management/Payer account
- `deploy-in-linked-account.yaml` deployed in each member account that runs DevOps Agent, with `IncludeDevOpsAgentModule=yes`
- Data Collection account with the main `deploy-data-collection.yaml` stack and `IncludeDevOpsAgentModule=yes`

DevOps Agent is a regional service. Set `RegionsInScope` in the main stack to every region where Agent Spaces exist; the default is the deployment region only.

### S3 Bucket Layout

```
s3://{DestinationBucket}/
│
├── account-list/                                   ← Account Collector reads these (optional)
│   └── account-list.csv                            ← format: account_id,account_name,payer_id
│
└── devops-agent/
    ├── devops-agent-agent-spaces-data/
    ├── devops-agent-tasks-data/
    ├── devops-agent-journal-records-data/
    ├── devops-agent-tool-usage-data/
    └── devops-agent-account-usage-data/
        └── payer_id={X}/
            └── year={YYYY}/
                └── month={MM}/
                    └── devops-agent-<dataset>-<account_id>-<YYYYMMDD-HHMMSS>.json   ← JSONL
```

`payer_id`, `year` and `month` are **Athena partition keys**. `account_id` and `region` are regular columns because one Lambda invocation writes one file per dataset covering all regions of an account.

### Parameters

| Parameter | Description | Default |
|---|---|---|
| `RegionsInScope` | Comma-separated regions where Agent Spaces exist | Deployment region |
| `Schedule` | EventBridge schedule expression (wired to `ScheduleFrequent` in the main stack) | `rate(1 day)` |
| `TaskLookbackDays` | Collect tasks created within this many days (1–90) | `14` |
| `JournalLookbackDays` | Fetch journals for executions running or updated within this many days (1–90). Must be ≥ the collection interval | `3` |
| `Boto3LayerArn` | CID Boto3 Lambda layer. Required until the Lambda runtime's bundled boto3 includes the `devops-agent` service | Set by the main stack |
| `DatabaseName` | Athena database | `optimization_data` |
| `MultiAccountRoleName` | Cross-account IAM role name in member accounts | `Optimization-Data-Multi-Account-Role` |

Lambda: Python 3.13, 2048 MB, 900 s timeout. Files are staged in `/tmp` (512 MB), which is enough for daily increments; see Known Constraints for backfills.

### IAM Permissions Required in Member Accounts

Granted by `DevOpsAgentModulePolicy` in `deploy-in-linked-account.yaml` (read-only; the IAM service prefix is `aidevops`, not `devops-agent`):

- `aidevops:ListAgentSpaces`
- `aidevops:GetAgentSpace`
- `aidevops:ListBacklogTasks`
- `aidevops:GetBacklogTask`
- `aidevops:ListExecutions`
- `aidevops:ListJournalRecords`
- `aidevops:GetAccountUsage`

`Resource: "*"` is required because the list and account-usage actions do not support resource-level permissions.

If an Agent Space is encrypted with a customer-managed KMS key (`kms_key_arn` column is not null), the cross-account role also needs `kms:Decrypt` on that key via the `aidevops` service, or `ListJournalRecords` fails for that space.

---

## Athena Tables

All tables share these columns:

| Column | Type | Definition |
|---|---|---|
| `account_id` | string | Member account the data was collected from |
| `account_name` | string | Account name from the account list / Organizations |
| `region` | string | Region of the Agent Space |
| `collection_time` | string | ISO-8601 UTC timestamp of the collection run |
| `payer_id` | string | Management/payer account ID (partition) |
| `year`, `month` | string | Collection year and month (partitions) |

### `optimization_data.devops_agent_agent_spaces_data`
One row per Agent Space per run.

| Column | Type | Definition |
|---|---|---|
| `agent_space_id` | string | Agent Space identifier |
| `agent_space_name` | string | Display name |
| `description` | string | Description |
| `locale` | string | Configured locale |
| `kms_key_arn` | string | Customer-managed KMS key, if any |
| `preferences` | string | JSON of the space preferences |
| `created_at`, `updated_at` | string | Timestamps |

### `optimization_data.devops_agent_tasks_data`
One row per backlog task per run, joined with its primary execution.

| Column | Type | Definition |
|---|---|---|
| `agent_space_id`, `agent_space_name` | string | Owning Agent Space |
| `task_id` | string | Backlog task identifier |
| `task_type` | string | `INVESTIGATION`, `EVALUATION`, `SYSTEM_LEARNING`, `CUSTOM`, … |
| `title`, `description` | string | Task title and description (description truncated to 4,000 chars) |
| `status`, `status_reason` | string | Task status and reason |
| `priority` | string | Task priority |
| `primary_task_id` | string | Parent task for linked/sub tasks |
| `has_linked_tasks` | boolean | Whether the task has sub-tasks |
| `version` | int | Task version |
| `reference_system`, `reference_id`, `reference_url`, `reference_title`, `association_id` | string | External reference (alarm, ticket, …) that created the task |
| `metadata`, `support_metadata` | string | JSON blobs as returned by the API |
| `created_at`, `updated_at` | string | Task timestamps |
| `execution_id` | string | Primary execution |
| `agent_type` | string | Agent that ran the execution |
| `agent_sub_task` | string | Sub-task name for sub-agent executions |
| `execution_status` | string | Execution status |
| `parent_execution_id` | string | Parent execution for sub-agents |
| `execution_created_at`, `execution_updated_at` | string | Execution timestamps |
| `execution_duration_seconds` | double | `updated - created` for terminal executions. Note: the agent appends journal records days later, so this can overstate active time; the dashboard's `task_summary_view` uses "active minutes" (sum of gaps ≤ 30 min between records) instead |

### `optimization_data.devops_agent_journal_records_data`
One row per journal record. Largest table; `content` holds the raw record.

| Column | Type | Definition |
|---|---|---|
| `agent_space_id`, `agent_space_name`, `task_id`, `task_type` | string | Context |
| `execution_id`, `agent_type`, `agent_sub_task` | string | Execution the record belongs to |
| `record_id` | string | Journal record identifier |
| `record_type` | string | `message`, `usage_metrics`, `utilization`, `task_summary`, … |
| `created_at` | string | Record timestamp |
| `user_id`, `user_type` | string | Who caused the record (user or agent) |
| `message_role` | string | `user` or `assistant` for message records |
| `agent_name` | string | Agent name from `usage_metrics` |
| `text_preview` | string | First 1,000 chars of the text content |
| `tool_use_count`, `tool_error_count` | int | Tool calls in this record and how many returned an error |
| `tool_names` | array<string> | Distinct tool names in this record |
| `input_tokens`, `output_tokens`, `total_tokens`, `cache_read_input_tokens`, `cache_write_input_tokens` | bigint | Token usage from `usage_metrics` |
| `duration_seconds` | double | Turn duration from `usage_metrics` |
| `context_window_utilization` | double | From `utilization` records |
| `content_size_bytes` | bigint | Size of the raw `content` |
| `content` | string | Raw record content, verbatim JSON. Use `json_extract` in Athena for anything not promoted |

### `optimization_data.devops_agent_tool_usage_data`
One row per tool invocation.

| Column | Type | Definition |
|---|---|---|
| `agent_space_id`, `agent_space_name`, `task_id`, `task_type`, `execution_id`, `agent_type`, `agent_sub_task` | string | Context |
| `record_id`, `record_type`, `created_at` | string | Journal record the call was found in |
| `source` | string | Same as `record_type`, kept for filtering |
| `tool_name` | string | Tool called (e.g. `query_cloudwatch_logs`, `get_metric_data`, skill tools) |
| `tool_use_id` | string | Links the `toolUse` to its `toolResult` |
| `tool_use_count` | int | 1 per message tool call; aggregated count from `usage_metrics` |
| `status` | string | `success` / `error` from the matching tool result, null if no result was found |
| `message_role` | string | Role of the message containing the call |

### `optimization_data.devops_agent_account_usage_data`
One row per account and region per run: monthly DevOps Agent hours by category, from `GetAccountUsage`.

| Column | Type | Definition |
|---|---|---|
| `usage_period_start`, `usage_period_end` | string | Current billing period |
| `investigation_hours`, `investigation_hours_limit` | double | Hours used and limit |
| `evaluation_hours`, `evaluation_hours_limit` | double | |
| `system_learning_hours`, `system_learning_hours_limit` | double | |
| `on_demand_hours`, `on_demand_hours_limit` | double | |
| `grader_hours`, `grader_hours_limit` | double | |

A `_limit` of `-1` means the API returned no limit.

---

## Athena Views

Views are created by the CID framework dashboard (`cid-cmd deploy --dashboard-id devops-agent`), not by this module. They deduplicate the raw tables and add derived measures:

| View | Purpose |
|---|---|
| `devops_agent_tasks_view` | Latest snapshot per task |
| `devops_agent_journal_records_view` | Latest snapshot per record (without `content`) |
| `devops_agent_task_summary_view` | Per task: records, tool calls, errors, tokens, active minutes, first/last record |
| `devops_agent_tool_usage_view` | Deduplicated tool calls |
| `devops_agent_account_usage_view` | Latest usage per account, region and period |
| `devops_agent_findings_view` | Task-summary records with the agent's conclusion text |

---

## Example Queries

**Tasks per Agent Space and type, last 30 days:**
```sql
SELECT agent_space_name, task_type, status, count(*) AS tasks
FROM optimization_data.devops_agent_tasks_view
WHERE from_iso8601_timestamp(created_at) > current_timestamp - interval '30' day
GROUP BY 1, 2, 3
ORDER BY tasks DESC
```

**Most used tools and their error rate:**
```sql
SELECT tool_name,
       sum(tool_use_count) AS calls,
       sum(CASE WHEN status = 'error' THEN tool_use_count ELSE 0 END) AS errors,
       round(100.0 * sum(CASE WHEN status = 'error' THEN tool_use_count ELSE 0 END) / sum(tool_use_count), 1) AS error_pct
FROM optimization_data.devops_agent_tool_usage_view
GROUP BY 1
ORDER BY calls DESC
LIMIT 25
```

**Token usage per investigation:**
```sql
SELECT task_id, agent_space_name,
       sum(input_tokens) AS input_tokens,
       sum(output_tokens) AS output_tokens,
       sum(cache_read_input_tokens) AS cache_read_tokens
FROM optimization_data.devops_agent_journal_records_view
WHERE record_type = 'usage_metrics'
GROUP BY 1, 2
ORDER BY input_tokens DESC
LIMIT 20
```

**CloudWatch Logs Insights bytes scanned by the agent (from raw `content`):**
```sql
SELECT task_id,
       sum(cast(json_extract_scalar(content, '$.message.content[0].toolResult.content[0].json.statistics.bytesScanned') AS double)) / 1e9 AS gb_scanned
FROM optimization_data.devops_agent_journal_records_data
WHERE record_type = 'message'
  AND message_role = 'user'
  AND content LIKE '%bytesScanned%'
GROUP BY 1
ORDER BY gb_scanned DESC
```

**Monthly hours against limits:**
```sql
SELECT account_id, region, usage_period_start,
       investigation_hours, investigation_hours_limit,
       round(100.0 * investigation_hours / nullif(investigation_hours_limit, -1), 1) AS investigation_pct
FROM optimization_data.devops_agent_account_usage_view
ORDER BY investigation_pct DESC NULLS LAST
```

---

## Known Constraints

**Journal volume.** A single investigation can produce several thousand records, and `content` is kept in full. Expect the journal table to dominate storage (tens of KB per record for tool results). Daily increments fit in the Lambda's 512 MB `/tmp`; a multi-month backfill does not and should be run outside Lambda (or with the lookbacks raised gradually).

**Regions.** DevOps Agent is regional and the module only visits `RegionsInScope`. Agent Spaces in other regions are not collected.

**Chats are not collected.** `ListChats` is not part of this module; only backlog tasks and their executions are.

**`utilization` records** are cumulative per-turn snapshots. Their tool counts duplicate the message-level tool calls, so the module keeps only the tool names from them and does not emit tool-usage rows.

**Permissions errors inside tool results** (e.g. `AccessDenied` returned to the agent by an AWS API) are stored in `content`, not surfaced as the tool call's `status`; `status` reflects the tool runtime result only.

**Data sensitivity.** `content` contains the agent's full conversation, including log lines and resource identifiers it read. Treat the journal table and the data bucket with the same access controls as the source accounts' CloudWatch Logs.
