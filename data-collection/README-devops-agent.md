# AWS DevOps Agent Data Collection Module

## Overview

The DevOps Agent module collects operational data from [AWS DevOps Agent](https://aws.amazon.com/devops-agent/) across all accounts and regions in your AWS Organization: backlog tasks (investigations, evaluations, system learning, release readiness reviews, custom agents) with their executions, the **journal records** the agent writes while it works, every tool call it made, chats discovered through those journals, and the monthly agent hours per account.

The result is a queryable record of what the agent did, in which account and Agent Space, with which tools, what it found and what it proposed. It feeds the **AWS DevOps Agent Dashboard** in the [CID framework](https://github.com/aws-solutions-library-samples/cloud-intelligence-dashboards-framework) (`dashboards/devops-agent/`).

**Schedule:** Daily (`ScheduleFrequent`, configurable)
**Collection scope:** All accounts in scope × regions in `RegionsInScope`
**Output:** Four Athena tables in the `optimization_data` database

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
                ListAgentSpaces          → the spaces to visit
                ListBacklogTasks         → tasks created in the last TaskLookbackDays
                ListExecutions           → per task, joined with the task row      → tasks
                ListJournalRecords       → per execution that is running or was updated
                                           in the last JournalLookbackDays           → journal-records, tool-usage
                ListJournalRecords       → per chat discovered in those journals     → tasks (CHAT), journal-records, tool-usage
            → Writes JSONL files to S3
      → Glue Crawler — registers new partitions
```

Tasks are processed in parallel inside the Lambda (`ThreadPoolExecutor`, 8 workers) because one `ListJournalRecords` page holds at most 100 records and a long investigation can have several thousand. The Lambda stops starting new work 90 s before its 900 s timeout and defers the rest to the next run; nothing is lost because the next run re-collects anything still inside the lookback windows.

### Incremental collection

The module is stateless. Each run collects:

- every task created within `TaskLookbackDays` (default 14), so status changes after creation are captured by re-collection;
- journal records only for executions that are still running or were updated within `JournalLookbackDays` (default 3). Finished executions older than that were already captured by an earlier run;
- chats have no status or update timestamp, so the module reads their newest journal record first (`ListJournalRecords` with `limit=1, order=DESC`) and only reads the full journal when that record is inside `JournalLookbackDays`.

Because the same task or record can be written more than once, the dashboard views keep the latest snapshot per key with `ROW_NUMBER() OVER (PARTITION BY <key> ORDER BY collection_time DESC)`. Query the views, not the raw tables, unless you want the collection history.

### How journal records are stored

A journal record is `{recordId, recordType, createdAt, userReference, content}`. `content` is free-form JSON that differs per `record_type`. The module does **not** store the raw `content`; it parses each record once at collection time and writes only the fields the dashboard needs:

| `record_type` | Columns filled |
|---|---|
| `message` / `agent_message` | `message_role`, `text_preview`, `tool_use_count`, `tool_error_count`; one `tool-usage` row per tool call |
| `finding` | `title`, `text`, `finding_type` (Root cause / Cause / Hypothesis), `resolution` (Ruled in / Ruled out / Open), `resolution_reason`, `related_resources`, `supporting_observations` |
| `symptom`, `observation`, `investigation_gap`, `investigation_summary`, `evaluation_summary`, `investigation_result` | `title`, `text`, `related_resources` |
| `mitigation_summary` | `title` (the action), `text` (action + reasoning), `plan_steps` |
| `usage_metrics` | `agent_name`, `text_preview` |
| anything else | `title`, `text_preview` from the first text-like field |

**Tool usage** rows come from the same records. A `toolUse` block in an assistant `message` (record *N*) is matched to its `toolResult` block in the following user `message` (record *N+1*) by `toolUseId`, which gives each call a `status`, and for errors an `error_class` (guardrail, permission denied, not found, invalid input, …) and the error text. For `use_aws` calls the AWS service and operation are recorded. For CloudWatch Logs Insights queries the module reads the `statistics` block the service returns (`bytesScanned`, `recordsScanned`, `recordsMatched`) and attaches it to the `start_query` call that started the query, so each query is counted once.

### How chats are discovered

The DevOps Agent API lists chats for the **calling identity only** (`ListChats` resolves the user from the session), so an account-wide collector cannot enumerate them. The module instead relies on the agent itself: its periodic System Learning tasks call the internal tool `list_power_chat_sessions`, and the resulting list of chat execution ids is in their journal. The module reads those ids with `ListJournalRecords` like any other execution and stores each chat as a task row with `task_type = CHAT`, together with its journal and tool rows. Coverage is best effort: a chat appears after the next System Learning run in its Agent Space, and chats in spaces where that task never runs are not collected.

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

If an Agent Space is encrypted with a customer-managed KMS key, the cross-account role also needs `kms:Decrypt` on that key via the `aidevops` service, or `ListJournalRecords` fails for that space.

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

### `optimization_data.devops_agent_tasks_data`
One row per backlog task per run, joined with its primary execution; plus one row per discovered chat (`task_type = CHAT`).

| Column | Type | Definition |
|---|---|---|
| `agent_space_id`, `agent_space_name` | string | Owning Agent Space |
| `task_id` | string | Backlog task identifier; the chat execution id for chats |
| `task_type` | string | `INVESTIGATION`, `EVALUATION`, `SYSTEM_LEARNING`, `RELEASE_READINESS_REVIEW`, `CUSTOM`, `CHAT`, … |
| `title` | string | Task title; for chats the chat title or the first user message |
| `status`, `status_reason` | string | Task status and reason (null for chats) |
| `priority` | string | Task priority |
| `primary_task_id` | string | Parent task for linked/sub tasks |
| `reference_system`, `reference_id`, `reference_url` | string | Incident reference of tasks created through a webhook or integration (CloudWatch alarm via webhook, Datadog, ServiceNow, …). Null for tasks started in the console |
| `linked_recommendations` | int | Recommendations linked to the task (> 0 when an investigation was started from a recommendation) |
| `created_at`, `updated_at` | string | Task timestamps |
| `execution_id` | string | Primary execution |
| `agent_type` | string | Agent that ran the execution (`chat` for chats) |
| `execution_status` | string | Execution status |
| `execution_created_at`, `execution_updated_at` | string | Execution timestamps |
| `execution_duration_seconds` | double | `updated - created` for terminal executions. The agent can append journal records days later, so the dashboard's `task_summary_view` uses "active minutes" (sum of gaps ≤ 30 min between records) instead |

### `optimization_data.devops_agent_journal_records_data`
One row per journal record. Largest table.

| Column | Type | Definition |
|---|---|---|
| `agent_space_id`, `agent_space_name`, `task_id`, `task_type` | string | Context |
| `execution_id`, `agent_type` | string | Execution the record belongs to |
| `record_id` | string | Journal record identifier |
| `record_type` | string | `message`, `agent_message`, `finding`, `observation`, `symptom`, `investigation_gap`, `mitigation_summary`, `usage_metrics`, `utilization`, … |
| `created_at` | string | Record timestamp |
| `user_type` | string | Who caused the record (user or agent) |
| `message_role` | string | `user` or `assistant` for message records |
| `agent_name` | string | Agent name from `usage_metrics` |
| `text_preview` | string | First 500 chars of the text content |
| `tool_use_count`, `tool_error_count` | int | Tool calls in this record and how many returned an error |
| `title` | string | Title of a finding, symptom, gap, mitigation (the action) or summary |
| `text` | string | Body text (up to 2,000 chars): finding description, gap text, mitigation action + reasoning |
| `finding_type` | string | `Root cause`, `Cause`, `Hypothesis` for `finding` records |
| `resolution` | string | `Ruled in`, `Ruled out`, `Open` for `finding` records |
| `resolution_reason` | string | Why a hypothesis was ruled in or out |
| `related_resources` | array<string> | Resources (ARNs or names) named in the record |
| `supporting_observations` | int | Observations backing a finding |
| `plan_steps` | int | Steps in a mitigation's execution plan |

### `optimization_data.devops_agent_tool_usage_data`
One row per tool invocation.

| Column | Type | Definition |
|---|---|---|
| `agent_space_id`, `agent_space_name`, `task_id`, `task_type`, `execution_id`, `agent_type` | string | Context |
| `record_id`, `record_type`, `created_at`, `message_role` | string | Journal record the call was found in |
| `tool_name` | string | Tool called (e.g. `use_aws`, `query_cloudwatch_logs`, `fs_read`, `subagent`) |
| `tool_use_id` | string | Links the `toolUse` to its `toolResult` |
| `status` | string | `success` / `error` from the matching tool result, null if no result was found |
| `is_error` | int | 1 when `status = error` |
| `aws_service`, `aws_operation`, `aws_region` | string | For AWS API calls: service, operation and region called |
| `tool_category` | string | `Logs`, `Metrics`, `CloudTrail`, `AWS API`, `Skills`, `Sub-agent`, `Files & shell`, `Source control`, `Tasks`, … |
| `skill_name` | string | Skill loaded, read or edited by this call, if any |
| `error_class` | string | For errors: `Blocked by guardrail`, `Permission denied`, `Not found`, `Invalid input`, `Throttled`, `Timeout`, `Output too large`, … |
| `denied_action` | string | IAM action named in an access-denied error |
| `error_message` | string | First 200 chars of the error text |
| `log_group` | string | Log group queried (Logs Insights, FilterLogEvents) |
| `logs_query_id` | string | Logs Insights query id |
| `query_window_hours` | double | Time window of a log or CloudTrail query |
| `logs_bytes_scanned`, `logs_records_scanned`, `logs_records_matched` | double | Logs Insights statistics, attached to the `start_query` call that started the query |

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

Views are created by the CID framework dashboard (`cid-cmd deploy --dashboard-id devops-agent`), not by this module. They deduplicate the raw tables and add derived measures such as active minutes per task, investigation results and chat intents.

---

## Example Queries

**Tasks per Agent Space and type, last 30 days:**
```sql
SELECT agent_space_name, task_type, status, count(DISTINCT task_id) AS tasks
FROM optimization_data.devops_agent_tasks_data
WHERE from_iso8601_timestamp(created_at) > current_timestamp - interval '30' day
GROUP BY 1, 2, 3
ORDER BY tasks DESC
```

**Tool errors by cause:**
```sql
SELECT error_class, tool_name, aws_service, count(*) AS errors, count(DISTINCT task_id) AS tasks_affected
FROM optimization_data.devops_agent_tool_usage_data
WHERE is_error = 1
GROUP BY 1, 2, 3
ORDER BY errors DESC
```

**Root causes identified per investigation:**
```sql
SELECT task_id, count_if(finding_type = 'Root cause') AS root_causes, count_if(resolution = 'Ruled out') AS ruled_out
FROM optimization_data.devops_agent_journal_records_data
WHERE record_type = 'finding'
GROUP BY 1
ORDER BY root_causes DESC
```

**Mitigations the agent proposed:**
```sql
SELECT agent_space_name, task_id, created_at, title AS action, plan_steps
FROM optimization_data.devops_agent_journal_records_data
WHERE record_type = 'mitigation_summary'
ORDER BY created_at DESC
```

**CloudWatch Logs Insights data scanned by the agent, per log group:**
```sql
SELECT log_group, count(*) AS queries, round(sum(logs_bytes_scanned) / 1e9, 2) AS gb_scanned
FROM optimization_data.devops_agent_tool_usage_data
WHERE logs_bytes_scanned IS NOT NULL
GROUP BY 1
ORDER BY gb_scanned DESC
```

**Monthly hours against limits:**
```sql
SELECT account_id, region, usage_period_start,
       investigation_hours, investigation_hours_limit,
       round(100.0 * investigation_hours / nullif(investigation_hours_limit, -1), 1) AS investigation_pct
FROM optimization_data.devops_agent_account_usage_data
ORDER BY usage_period_start DESC
```

---

## Known Constraints

**Journal volume.** A single investigation can produce several thousand records. Daily increments fit in the Lambda's 512 MB `/tmp`; a multi-month backfill does not and should be run outside Lambda (or with the lookbacks raised gradually).
