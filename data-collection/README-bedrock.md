# Amazon Bedrock Invocation Logs Data Collection Module

## Overview

The Bedrock module collects [Amazon Bedrock model-invocation logs](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)
that customers deliver to Amazon S3, and makes them queryable in Athena for
usage, token-consumption, and prompt/response analysis.

This module is **pull-based**. It does **not** enable Bedrock logging for you and
it does **not** make any changes in your source accounts. You enable Bedrock
invocation logging yourself (per account and region, as you choose), grant the
collection Lambda read access to your logs bucket with a bucket policy, and the
module copies the logs into the central data-collection bucket on a schedule.

**Schedule:** Daily
**Collection scope:** The S3 location(s) you list in `BedrockSourceBuckets`
**Output:** One Athena table (`bedrock_logs`) in the `optimization_data`
database. The flattened `bedrock_invocations_view` is created by `cid-cmd`
during dashboard deployment, not by this module.

---

## Why this module is pull-based (customer-managed logging)

Amazon Bedrock allows only **one** model-invocation-logging configuration per
account/region, and enabling it captures prompt and response content. Turning
that on across an organization is a decision that belongs to the customer, not a
side effect of a data-collection stack. So this module:

- **Never mutates your accounts.** It only reads the S3 bucket(s) you point it at.
- **Respects any logging config you already have.** You keep full control of what
  is logged, in which accounts and regions.
- **Reads only Bedrock invocation logs.** The collection Lambda's role has one
  fixed-size read policy, so there is no limit on how many source locations you
  list. It allows `s3:GetObject` only on Bedrock's delivery path
  (`.../AWSLogs/{account}/BedrockModelInvocationLogs/...`, with or without a
  key prefix) and `s3:ListBucket` only for the prefixes the collector walks.
  Cross-account source buckets must also grant the role access in their bucket
  policy, and `BedrockSourceBuckets` decides which locations are collected.

This mirrors the pull-based pattern used by the Kiro User Activity module.

---

## How it works

```
You enable Bedrock invocation logging (S3 delivery) in your account(s)/region(s)
  → Bedrock writes .json.gz logs to your bucket (at the root by default, or under
    the keyPrefix you set)
      → EventBridge Scheduler (daily) triggers the collection Lambda
          → Lambda lists each source bucket and reconciles the last 30 days
            against what it has already imported (the destination is the checkpoint)
          → For each new object: gunzip, flatten to the table schema, write
            JSONL to the destination under a Hive-partitioned path
          → Registers the (account_id, region, year, month, day) partition in Glue
              → Queryable in Athena: SELECT * FROM optimization_data.bedrock_logs
```

There is no Glue crawler, no Glue ETL job, and no Step Function — the single
collection Lambda does the copy, the flatten, and the partition registration.
Because every partition is registered explicitly (partition projection is not
used), `SELECT * FROM bedrock_logs` works with no mandatory `WHERE` filter.

---

## Setup

### 1. Enable Bedrock model-invocation logging (in each source account/region)

Enable logging with **S3 delivery** so Bedrock writes logs to a bucket you own.
You can do this in the Bedrock console (Settings → Model invocation logging) or
with the CLI, for example:

```bash
aws bedrock put-model-invocation-logging-configuration \
  --region us-east-1 \
  --logging-config '{
    "s3Config": {
      "bucketName": "YOUR-BEDROCK-LOGS-BUCKET-NAME"
    },
    "textDataDeliveryEnabled": true,
    "imageDataDeliveryEnabled": true,
    "embeddingDataDeliveryEnabled": true
  }'
```

Repeat for each account and region you want collected. The module reads whatever
you have configured — it does not change these settings.

`keyPrefix` is optional. For root delivery, add only the bucket name to
`BedrockSourceBuckets`. If you set a non-empty `keyPrefix`, append it to that
bucket's entry after the first `/`. Do not include `s3://`, and do not end an
entry with `/`.

### 2. Enable the module

Set `IncludeBedrockModule=yes` on the Data Collection stack and provide the S3
source location(s) in `BedrockSourceBuckets` (comma-separated). A bare bucket
means logs are under `AWSLogs/` at the root; `bucket/prefix` means logs are
under `prefix/AWSLogs/`. For example, this collects one root-delivery bucket
and one prefixed bucket:

```
bedrock-logs-111111111111-us-east-1,bedrock-logs-222222222222-us-east-1/model-invocation-logs
```

If your source buckets are encrypted with a customer-managed KMS key, add the
key ARN(s) to `DataBucketsKmsKeysArns`.

### 3. Grant the collection Lambda read access to each source bucket

After the stack deploys, the Bedrock module stack exposes a
**`BucketPolicyExample`** output. It is an illustrative policy for one source
bucket with the deployed `LambdaRoleArn` already populated. Apply a separate
statement pair to each source bucket and replace the bucket and prefix
placeholders to match its `BedrockSourceBuckets` entry.

For a bare bucket entry such as `my-bedrock-logs`, use:

```json
[
  {
    "Sid": "AllowCIDBedrockDataCollectionRead",
    "Effect": "Allow",
    "Principal": { "AWS": "<BedrockModule LambdaRoleArn output>" },
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::my-bedrock-logs/*"
  },
  {
    "Sid": "AllowCIDBedrockDataCollectionList",
    "Effect": "Allow",
    "Principal": { "AWS": "<BedrockModule LambdaRoleArn output>" },
    "Action": "s3:ListBucket",
    "Resource": "arn:aws:s3:::my-bedrock-logs",
    "Condition": { "StringLike": { "s3:prefix": "AWSLogs/*" } }
  }
]
```

For `my-bedrock-logs/model-invocation-logs`, change the object resource to
`arn:aws:s3:::my-bedrock-logs/model-invocation-logs/*` and the `s3:prefix`
condition to `model-invocation-logs/AWSLogs/*`. Always use the exact
`LambdaRoleArn` emitted by your stack; do not use a wildcard principal.

---

## Data model

### Table: `optimization_data.bedrock_logs`

Partitioned by `account_id`, `region`, `year`, `month`, `day` (all derived from
the Bedrock S3 delivery path, not stored in the row body).

| Column | Type | Notes |
|---|---|---|
| `schematype` | string | Bedrock log `schemaType` |
| `schemaversion` | string | Bedrock log `schemaVersion` |
| `timestamp` | string | ISO-8601 invocation time |
| `region` | string | Also a partition key |
| `requestid` | string | |
| `operation` | string | e.g. `InvokeModel` |
| `modelid` | string | e.g. `amazon.nova-micro-v1:0` |
| `errorcode` | string | Error code on failed invocations (empty on success) |
| `inferenceregion` | string | Region the model ran in (for cross-region profiles) |
| `requestmetadata` | map<string,string> | |
| `collection_time` | string | When the row was collected |
| `input` | struct | `inputbodyjson`, `inputcontenttype`, `inputtokencount` |
| `output` | struct | `outputbodyjson`, `outputcontenttype`, `outputtokencount` |
| `identity_arn` | string | Caller identity ARN |

The `input`/`output` bodies are kept as nested JSON strings so token counts and
prompt/response content can be extracted per query.

### View: `optimization_data.bedrock_invocations_view`

A flattened, dashboard-friendly view over `bedrock_logs` that extracts token
usage and prompt/response previews from the nested body JSON. `cid-cmd` creates
and maintains this view automatically when you deploy or update the Bedrock
Unified Insights Lens Dashboard, so you do not need to create it by hand. To
query the raw data before deploying the dashboard, use the sample queries below
against `bedrock_logs` directly.

---

## Sample Athena queries

Query the whole table (no filter required):

```sql
SELECT * FROM optimization_data.bedrock_logs LIMIT 100;
```

Invocations per model, last 30 days:

```sql
SELECT modelid, count(*) AS invocations
FROM optimization_data.bedrock_logs
WHERE from_iso8601_timestamp(timestamp) >= date_add('day', -30, current_timestamp)
GROUP BY modelid
ORDER BY invocations DESC;
```

Token usage per account and model:

```sql
SELECT
  account_id,
  modelid,
  sum(input.inputtokencount)  AS input_tokens,
  sum(output.outputtokencount) AS output_tokens
FROM optimization_data.bedrock_logs
GROUP BY account_id, modelid
ORDER BY output_tokens DESC;
```

Prompt / response previews:

```sql
SELECT
  account_id,
  region,
  timestamp,
  modelid,
  COALESCE(
    json_extract_scalar(input.inputbodyjson, '$.messages[0].content[0].text'),
    json_extract_scalar(input.inputbodyjson, '$.prompt'),
    json_extract_scalar(input.inputbodyjson, '$.inputText')
  ) AS prompt_preview,
  COALESCE(
    json_extract_scalar(output.outputbodyjson, '$.output.message.content[0].text'),
    json_extract_scalar(output.outputbodyjson, '$.content[0].text'),
    json_extract_scalar(output.outputbodyjson, '$.outputText')
  ) AS response_preview
FROM optimization_data.bedrock_logs
ORDER BY timestamp DESC
LIMIT 50;
```

---

## Notes

- **No data appears until logging is enabled and the bucket policy is applied.**
  The table only shows rows once Bedrock has written logs to a source bucket and
  the collection Lambda can read them.
- **New accounts/regions are picked up automatically.** The collector registers
  each new partition it writes, so newly logged accounts and regions become
  queryable without any stack change or crawler run.
- **Re-runs are safe.** The destination bucket is the import checkpoint, so each
  run only copies objects it has not already imported; transient failures
  self-heal on the next run. The collector copies up to eight objects in
  parallel and registers each day's Athena partition as soon as that day is
  processed, including a partially processed day.
- **Backfills can require several invocations.** Scheduled runs reconcile the
  last 30 days, but elapsed time depends on the number and size of source
  objects rather than only the requested day count. The Lambda has a 10-minute
  limit and begins a clean shutdown with approximately 60 seconds remaining.
  A high-volume one-day window can therefore take most of an invocation, and a
  30-day or historical backfill can require several invocations.

  Invoke asynchronously so the AWS CLI does not wait for the Lambda result.
  Start with a one-day verification:

  ```bash
  aws lambda invoke --function-name CID-DC-bedrock-Lambda \
    --region <data-collection-region> \
    --invocation-type Event \
    --payload '{"days": 1}' --cli-binary-format raw-in-base64-out \
    /dev/stdout
  aws logs tail /aws/lambda/CID-DC-bedrock-Lambda \
    --region <data-collection-region> --follow
  ```

  To reconcile 30 days or import a wider history, change `days`:

  ```bash
  aws lambda invoke --function-name CID-DC-bedrock-Lambda \
    --region <data-collection-region> \
    --invocation-type Event \
    --payload '{"days": 30}' --cli-binary-format raw-in-base64-out \
    /dev/stdout
  ```

  The asynchronous response confirms only that Lambda accepted the request.
  Wait for the final JSON result in CloudWatch Logs. If it contains
  `"stopped_early": true`, repeat the same command after the current invocation
  finishes. Already imported objects are skipped. Do not run overlapping
  invocations.
- **Failures are visible.** If any object fails to import, the Lambda raises after
  the run (surfacing on the `Errors` metric) instead of returning success, so
  gaps are not hidden.
