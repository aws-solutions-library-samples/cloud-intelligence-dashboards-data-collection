# Hello DC — sample data collection module

Hello DC is a minimal, working CID data collection module for developers to copy. It shows how to build a module on the **common Lambda layer** (`data-collection/deploy/source/common`). It also shows how to write data that a **pre-created Glue table with partition projection** reads directly, without a crawler.

It collects the Amazon RDS major engine version support lifecycle (`rds:DescribeDBMajorEngineVersions`) for each region in scope.

## Why this API

- **No new cross-account permissions.** The Lambda calls the API in the **data collection account** with its own role. It never assumes the management or linked account roles. Those roles only trust an explicit list of module Lambda roles, so a module that assumes them needs a trust update in every payer or linked account. Installing Hello DC changes nothing outside its own stack.
- **Already used by the framework.** `module-reference.yaml` already grants `rds:DescribeDBMajorEngineVersions` to its Lambda role.
- **A nested response.** Each item contains a list of structures (`SupportedEngineLifecycles`), which shows how compound API values map to `array<struct<...>>` columns.

The module still runs on the main state machine with `CollectionType: Payers`. The account collector supplies each payer in the event, so the output is keyed by payer without the module calling AWS Organizations itself.

## Files

| File | Purpose |
|---|---|
| `module-hello-dc.yaml` | The module stack: Lambda (inline code), its role, the common layer, the Glue table, Step Function, schedule |
| `README.md` | This file |

The common layer source lives in `data-collection/deploy/source/common/`. It's built by `data-collection/utils/layer-utils/common-layer-build.sh`.

## Data layout

```
s3://<DestinationBucket>/hello-dc/hello-dc-sample-data/year=YYYY/month=MM/day=DD/<payer_id>_YYYY_MM_DD.json
```

Each file is JSON Lines, with one record per engine major version per region. A rerun on the same day overwrites that day's file.

**Naming rule for all modules:** the date is the only partition. If a module writes one file per account and/or region, it adds them to the file name rather than adding partition columns:

```
.../year=YYYY/month=MM/day=DD/<payer_id>[_<account_id>][_<region>]_YYYY_MM_DD.json
```

`DcUtils.date_partitioned_key(prefix, sub_name, when, payer_id, account_id=None, region=None)` builds this key. CID dashboard queries are light and filter on date, so extra partitions on account or region would only add projection overhead. Hello DC writes one cross-region file per payer, so it uses `<payer_id>` alone.

## Table: `hello_dc_sample_data`

| Column | Type | Source |
|---|---|---|
| `engine` | `string` | API |
| `majorengineversion` | `string` | API |
| `supportedenginelifecycles` | `array<struct<lifecyclesupportname:string, lifecyclesupportstartdate:timestamp, lifecyclesupportenddate:timestamp>>` | API |
| `region` | `string` | Added by the collector |
| `payer_id` | `string` | Added by the common layer |
| `collection_time` | `timestamp` | Added by the common layer |
| `year`, `month`, `day` | `string` (partition) | Projected from the S3 path |

**Partition projection.** The table sets `projection.enabled` and `storage.location.template`, so Athena computes the `year`/`month`/`day` partitions from the S3 path. There's no crawler, no `MSCK REPAIR`, and no stale partitions, and new days are queryable as soon as the file lands. Filter on the partition columns to limit the data scanned.

**Rules for the table schema:**
1. Columns come from the actual API response shape. Compound values become `struct`, `array`, or `map`, never a JSON `string`. The one exception is a field whose shape genuinely varies; see `.ai/specs/coding-standards.md` §1.8.
2. The Lambda conforms every record to the table before writing it. `SAMPLE_SCHEMA` in the inline code is a `common.record_schema.RecordSchema` with the same column list as the table, written with the API's spelling. Its types are parsed when the module loads, so a typo fails at cold start. `SAMPLE_SCHEMA.conform_all(records)` then does the following:
   - drops fields the table doesn't declare
   - writes missing fields as `null`
   - recurses into structs and arrays
   - writes timestamps as `yyyy-MM-dd HH:mm:ss.SSS` for the JSON SerDe

   If you add a column, change `SAMPLE_SCHEMA` and `SampleTable` together.

## How the module uses the common layer

```python
class HelloDcModule(DataCollectionModule):
    MODULE = "hello-dc"
    COLLECTORS = (Collector("sample", collect_sample, scope=Collector.GLOBAL),)

    def session_for(self, region):         # credentials: own role, no AssumeRole
    def output_key(self, name, region):    # S3 key: the Hive-style layout above
    def conform(self, name, records):      # record shape: conform to SAMPLE_SCHEMA
```

- **`Collector.GLOBAL`** runs the collector once per invocation. The collector loops over the regions in scope itself, so all regions land in one file per payer per day. With `Collector.REGIONAL`, every region would write to the same key.
- **`ctx.sweep(...)`** wraps each region's API calls. If one region fails, the module records a partial success (`207`) in the Data Collection Monitor log instead of losing the other regions.
- **The superclass handles the rest:** payer and region resolution from the event, record enrichment (`payer_id`, `collection_time`), JSONL upload, and the `logs/modules/` status entry.

## Build and deploy

These steps assume the data collection stack is already deployed, here with the default `CID-DC-` prefix.

```bash
# 1. Build the common layer -> data-collection/deploy/layers/common-layer.zip
./data-collection/utils/layer-utils/common-layer-build.sh

# 2. Upload templates, layers and Step Function definitions to your CFN bucket
./data-collection/utils/upload.sh <cfn-bucket>

# 3. Deploy the module stack in the data collection account
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws cloudformation deploy \
  --stack-name CID-DC-hello-dc \
  --template-file data-collection/samples/hello-dc/module-hello-dc.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    DestinationBucket=cid-data-$ACCOUNT \
    DestinationBucketARN=arn:aws:s3:::cid-data-$ACCOUNT \
    CodeBucket=<cfn-bucket> \
    StepFunctionExecutionRoleARN=arn:aws:iam::$ACCOUNT:role/CID-DC-StepFunctionExecutionRole \
    SchedulerExecutionRoleARN=arn:aws:iam::$ACCOUNT:role/CID-DC-SchedulerExecutionRole \
    AccountCollectorLambdaARN=arn:aws:lambda:<region>:$ACCOUNT:function:CID-DC-account-collector-Lambda \
    LambdaAnalyticsARN=arn:aws:lambda:<region>:$ACCOUNT:function:CID-DC-analytics-Lambda

# 4. Run it now instead of waiting for the schedule
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:<region>:$ACCOUNT:stateMachine:CID-DC-hello-dc-StateMachine
```

- `StepFunctionTemplate` and `CommonLayerKey` default to the `v3.14.9` paths that `upload.sh` writes. Override them if your version differs.
- To share one layer across modules, pass its ARN in `CommonLayerArn`. The stack then skips creating its own. When the data collection stack deploys a module that uses the layer, it creates `<ResourcePrefix>Common-Layer` and exports its ARN as `<data collection stack name>-CommonLayerArn`.
- A module added to the main repo uses that shared layer instead of creating its own. See `.ai/specs/coding-standards.md` §2.5.

## Query

```sql
SELECT engine, majorengineversion, region,
       l.lifecyclesupportname, l.lifecyclesupportstartdate, l.lifecyclesupportenddate
FROM optimization_data.hello_dc_sample_data
CROSS JOIN UNNEST(supportedenginelifecycles) AS t(l)
WHERE year = '2026' AND month = '10'
ORDER BY engine, majorengineversion, l.lifecyclesupportstartdate;
```

## Making your own module from this sample

1. Copy the folder, rename `CFDataName`, `MODULE`, the collector name and the table name.
2. Replace `collect_sample` with your API calls, and derive `SAMPLE_SCHEMA` and the table columns from the API's response shape. The botocore service model, or the API reference, is the source of truth.
3. Grant the API actions on the module's own `LambdaRole`, and only collect in the data collection account. If you need data from inside payer or linked accounts, the actions belong on the cross-account roles in `deploy-in-management-account.yaml` / `deploy-in-linked-account.yaml`. Your `LambdaRole` must also be added to those roles' trust lists, which means a redeploy in those accounts. Drop the `session_for` override to use the default AssumeRole behavior.
