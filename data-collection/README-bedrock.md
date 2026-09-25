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

**Schedule:** Daily (configurable via the `Schedule` parameter)
**Collection scope:** The S3 bucket(s) you list in `BedrockSourceBuckets`
**Output:** One Athena table (`bedrock_logs`) plus a saved view
(`bedrock_invocations_view`) in the `optimization_data` database

---

## Why this module is pull-based (customer-managed logging)

Amazon Bedrock allows only **one** model-invocation-logging configuration per
account/region, and enabling it captures prompt and response content. Turning
that on across an organization is a decision that belongs to the customer, not a
side effect of a data-collection stack. So this module:

- **Never mutates your accounts.** It only reads the S3 bucket(s) you point it at.
- **Respects any logging config you already have.** You keep full control of what
  is logged, in which accounts and regions.
- **Uses least-privilege reads.** The collection Lambda is granted `s3:GetObject`
  only under your Bedrock log prefix, and `s3:ListBucket` only for that prefix.

This mirrors the pull-based pattern used by the Kiro User Activity module.

---

## How it works

```
You enable Bedrock invocation logging (S3 delivery) in your account(s)/region(s)
  → Bedrock writes .json.gz logs to your bucket under model-invocation-logs/
      → EventBridge Scheduler (daily) triggers the collection Lambda
          → Lambda lists each source bucket and reconciles against what it has
            already imported (the destination is the checkpoint)
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
      "bucketName": "YOUR-BEDROCK-LOGS-BUCKET-NAME",
      "keyPrefix": "model-invocation-logs/"
    },
    "textDataDeliveryEnabled": true,
    "imageDataDeliveryEnabled": true,
    "embeddingDataDeliveryEnabled": true
  }'
```

Repeat for each account and region you want collected. The module reads whatever
you have configured — it does not change these settings.

### 2. Enable the module

Set `IncludeBedrockModule=yes` on the Data Collection stack and provide the
bucket name(s) in `BedrockSourceBuckets` (comma-separated), for example:

```
bedrock-logs-111111111111-us-east-1,bedrock-logs-222222222222-us-east-1
```

If your source buckets are encrypted with a customer-managed KMS key, add the
key ARN(s) to `DataBucketsKmsKeysArns`.

### 3. Grant the collection Lambda read access to each source bucket

After the stack deploys, the Bedrock module stack exposes a
**`BucketPolicyExample`** output — a ready-to-use policy statement scoped to your
log prefix and the collection Lambda role. Add it to each source bucket's policy,
replacing `YOUR-BEDROCK-LOGS-BUCKET-NAME` with the real bucket name:

```json
[
  {
    "Sid": "AllowCIDBedrockDataCollectionRead",
    "Effect": "Allow",
    "Principal": { "AWS": "<BedrockModule LambdaRoleArn output>" },
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::YOUR-BEDROCK-LOGS-BUCKET-NAME/model-invocation-logs/*"
  },
  {
    "Sid": "AllowCIDBedrockDataCollectionList",
    "Effect": "Allow",
    "Principal": { "AWS": "<BedrockModule LambdaRoleArn output>" },
    "Action": "s3:ListBucket",
    "Resource": "arn:aws:s3:::YOUR-BEDROCK-LOGS-BUCKET-NAME",
    "Condition": { "StringLike": { "s3:prefix": "model-invocation-logs/*" } }
  }
]
```

Use the exact `LambdaRoleArn` and prefix from the stack's `BucketPolicyExample`
output rather than hand-editing, so the principal and prefix match what was
deployed.

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
| `requestmetadata` | map<string,string> | |
| `payer_id` | string | Data-collection (payer) account id |
| `collection_time` | string | When the row was collected |
| `input` | struct | `inputbodyjson`, `inputcontenttype`, `inputtokencount` |
| `output` | struct | `outputbodyjson`, `outputcontenttype`, `outputtokencount` |
| `identity_arn` | string | Caller identity ARN |

The `input`/`output` bodies are kept as nested JSON strings so token counts and
prompt/response content can be extracted per query.

### View: `optimization_data.bedrock_invocations_view`

A flattened, dashboard-friendly view over `bedrock_logs` that extracts token
usage and prompt/response previews from the nested body JSON. It is provided as a
saved Athena query (`bedrock_invocations_view`); run it once in Athena to create
the view in your account, or use the sample queries below directly.

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
  sum(CAST(json_extract_scalar(output.outputbodyjson, '$.usage.inputTokens')  AS INTEGER)) AS input_tokens,
  sum(CAST(json_extract_scalar(output.outputbodyjson, '$.usage.outputTokens') AS INTEGER)) AS output_tokens
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
  self-heal and older gaps backfill on the next run.
