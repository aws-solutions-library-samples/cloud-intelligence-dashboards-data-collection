"""
Bedrock invocation end-to-end smoke test.

Generates real Amazon Bedrock model-invocation logs and (optionally) drives the
full pull-based collection pipeline to prove it works against a deployed stack:

    invoke Bedrock  ->  Bedrock delivers .json.gz to the source S3 bucket
        ->  run the collector Lambda  ->  it writes JSONL + registers a Glue
            partition  ->  the new day appears in the Athena table.

Invocations alternate between the Converse API and the raw InvokeModel API so
the generated logs contain BOTH usage schemas: Converse logs Bedrock's camelCase
format (inputTokens / outputTokens / stopReason) while InvokeModel logs the
model's own native format (for Claude: snake_case input_tokens / stop_reason /
cache_read_input_tokens). This exercises the dashboard view's COALESCE handling
across the different spellings.

By default it only sends invocations. Pass ``--collect`` to also wait for
delivery, trigger the collector, and verify the data is queryable in Athena.

The Bedrock model can be given explicitly with ``--model-id`` or read from a
CloudFormation stack output (``BedrockInferenceProfileArn``) with
``--stack-name``. Pipeline details (collector Lambda, destination bucket,
database, table) are discovered from the deployed data-collection Bedrock module
stack via ``--collector-stack-name`` (default
``CidDataCollectionStack-BedrockModule``*) or overridden individually.

Usage:
    # Just send 3 invocations (original behaviour)
    python test/test_bedrock_invocation.py \
        --profile awssteph+testing-RootAccountAdmin \
        --region us-east-1 \
        --model-id amazon.nova-micro-v1:0

    # Full end-to-end: invoke, collect, and verify in Athena
    python test/test_bedrock_invocation.py \
        --profile awssteph+testing-RootAccountAdmin \
        --region us-east-1 \
        --model-id amazon.nova-micro-v1:0 \
        --collect
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import boto3


def get_inference_profile_arn(session, stack_name):
    cfn = session.client("cloudformation")
    resp = cfn.describe_stacks(StackName=stack_name)
    outputs = resp["Stacks"][0].get("Outputs", [])
    for o in outputs:
        if o["OutputKey"] == "BedrockInferenceProfileArn":
            return o["OutputValue"]
    raise ValueError(f"BedrockInferenceProfileArn not found in stack {stack_name}")


def invoke_converse(client, model_id, i):
    """Call the Converse API. Bedrock logs usage in its own camelCase schema
    (inputTokens / outputTokens / stopReason), the same for every model."""
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": f"Converse test invocation {i}"}]}],
        inferenceConfig={"maxTokens": 10},
    )
    return resp["output"]["message"]["content"][0]["text"]


def _invoke_model_body(model_id):
    """Return a native-request body for invoke_model, matching the target
    model family. The response Bedrock logs is the model's OWN schema, which
    differs from Converse: Claude uses snake_case (input_tokens, stop_reason,
    cache_read_input_tokens); Nova uses its own nested usage object."""
    mid = model_id.lower()
    if "anthropic" in mid or "claude" in mid:
        return json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "InvokeModel test invocation"}],
        }).encode()
    if "nova" in mid:
        return json.dumps({
            "messages": [{"role": "user", "content": [{"text": "InvokeModel test invocation"}]}],
            "inferenceConfig": {"max_new_tokens": 10},
        }).encode()
    if "titan" in mid:
        return json.dumps({
            "inputText": "InvokeModel test invocation",
            "textGenerationConfig": {"maxTokenCount": 10},
        }).encode()
    # Fallback to the Nova/Converse-on-invoke shape
    return json.dumps({
        "messages": [{"role": "user", "content": [{"text": "InvokeModel test invocation"}]}],
        "inferenceConfig": {"max_new_tokens": 10},
    }).encode()


def invoke_invoke_model(client, model_id, i):
    """Call the raw InvokeModel API with the model's native body."""
    resp = client.invoke_model(
        modelId=model_id,
        body=_invoke_model_body(model_id),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["body"].read())
    # Extract text across the different native response shapes
    if "output" in result:                      # Nova
        return result["output"]["message"]["content"][0]["text"]
    if "content" in result:                      # Claude messages
        return result["content"][0]["text"]
    if "results" in result:                      # Titan
        return result["results"][0]["outputText"]
    if "completion" in result:                   # legacy Claude
        return result["completion"]
    return json.dumps(result)[:200]


def find_collector_stack(session, name_prefix):
    """Return the first stack whose name starts with name_prefix. The framework
    names the nested module stack CidDataCollectionStack-BedrockModule-<suffix>,
    so a prefix match locates it without knowing the random suffix."""
    cfn = session.client("cloudformation")
    paginator = cfn.get_paginator("describe_stacks")
    for page in paginator.paginate():
        for stack in page["Stacks"]:
            if stack["StackName"].startswith(name_prefix):
                return stack["StackName"]
    raise ValueError(f"No stack found with name starting '{name_prefix}'")


def discover_pipeline(session, collector_stack_prefix):
    """Resolve collector Lambda name, source buckets, destination bucket,
    database and table from the deployed Bedrock module stack + Lambda config."""
    cfn = session.client("cloudformation")
    lam = session.client("lambda")

    stack_name = find_collector_stack(session, collector_stack_prefix)
    outputs = {o["OutputKey"]: o["OutputValue"]
               for o in cfn.describe_stacks(StackName=stack_name)["Stacks"][0].get("Outputs", [])}
    lambda_arn = outputs.get("CollectorLambdaArn")
    if not lambda_arn:
        raise ValueError(f"CollectorLambdaArn output missing on stack {stack_name}")
    lambda_name = lambda_arn.split(":function:")[-1]

    env = lam.get_function_configuration(FunctionName=lambda_name).get(
        "Environment", {}).get("Variables", {})
    table_name = outputs.get("TableName", "")
    database = env.get("GLUE_DATABASE") or (table_name.split(".")[0] if "." in table_name else "optimization_data")
    table = env.get("GLUE_TABLE") or (table_name.split(".")[-1] if table_name else "bedrock_logs")

    return {
        "stack_name": stack_name,
        "lambda_name": lambda_name,
        "source_buckets": [b.strip() for b in env.get("SOURCE_BUCKETS", "").split(",") if b.strip()],
        "source_prefix": env.get("SOURCE_PREFIX", "model-invocation-logs/"),
        "dest_bucket": env.get("DEST_BUCKET", ""),
        "database": database,
        "table": table,
    }


def list_source_logs(session, buckets, source_prefix, day_path):
    """Return the set of .json.gz keys for the given day across all source
    buckets (as (bucket, key) tuples)."""
    s3 = session.client("s3")
    found = set()
    for bucket in buckets:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{source_prefix}AWSLogs/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".json.gz") and day_path in key:
                    found.add((bucket, key))
    return found


def wait_for_new_source_log(session, buckets, source_prefix, day_path, baseline,
                            timeout_s=420, poll_s=20):
    """Wait until a .json.gz for today's date appears that was not in the
    baseline set (i.e. delivered by the invocations we just sent). Returns the
    set of new keys, or an empty set on timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        current = list_source_logs(session, buckets, source_prefix, day_path)
        new = current - baseline
        if new:
            for bucket, key in sorted(new):
                print(f"  found new source log: s3://{bucket}/{key}")
            return new
        print(f"  {datetime.now().strftime('%H:%M:%S')} no new source log for {day_path} yet, waiting...")
        time.sleep(poll_s)
    return set()


def run_collector(session, lambda_name):
    lam = session.client("lambda")
    resp = lam.invoke(FunctionName=lambda_name, InvocationType="RequestResponse")
    payload = json.loads(resp["Payload"].read() or b"{}")
    return payload


def athena_query(session, database, sql, output_location, workgroup="primary", timeout_s=120):
    athena = session.client("athena")
    qid = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output_location},
        WorkGroup=workgroup,
    )["QueryExecutionId"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    if state != "SUCCEEDED":
        reason = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"].get(
            "StateChangeReason", "")
        raise RuntimeError(f"Athena query {state}: {reason}")
    rows = athena.get_query_results(QueryExecutionId=qid)["ResultSet"]["Rows"]
    return rows


def verify_athena(session, pipeline, today, athena_output):
    y, m, d = today.split("/")
    sql = (f"SELECT count(*) FROM {pipeline['database']}.{pipeline['table']} "
           f"WHERE year='{y}' AND month='{m}' AND day='{d}'")
    rows = athena_query(session, pipeline["database"], sql, athena_output)
    # rows[0] is the header, rows[1] the value
    count = int(rows[1]["Data"][0]["VarCharValue"]) if len(rows) > 1 else 0
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--stack-name", default="bedrock-logging",
                        help="Stack exposing BedrockInferenceProfileArn (used when --model-id is not given)")
    parser.add_argument("--model-id", default=None,
                        help="Bedrock model or inference profile ID (default: read from --stack-name output)")
    parser.add_argument("--count", type=int, default=4,
                        help="Number of invocations to send (alternates Converse / InvokeModel)")
    parser.add_argument("--collect", action="store_true",
                        help="After invoking, wait for delivery, run the collector, and verify in Athena")
    parser.add_argument("--collector-stack-name", default="CidDataCollectionStack-BedrockModule",
                        help="Name (or name prefix) of the deployed Bedrock data-collection module stack")
    parser.add_argument("--athena-output", default=None,
                        help="S3 location for Athena results (default: s3://<dest_bucket>/athena-results/)")
    parser.add_argument("--timeout", type=int, default=420,
                        help="Seconds to wait for Bedrock to deliver the log to S3")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)

    if args.model_id:
        model_id = args.model_id
    else:
        print(f"Looking up inference profile ARN from stack '{args.stack_name}'...")
        model_id = get_inference_profile_arn(session, args.stack_name)
    print(f"Using model: {model_id}")

    # When collecting, discover the pipeline and record which source logs
    # already exist for today BEFORE invoking, so we can wait specifically for
    # the ones our invocations produce (Bedrock S3 delivery lags a few minutes).
    pipeline = None
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    baseline = set()
    if args.collect:
        pipeline = discover_pipeline(session, args.collector_stack_name)
        if not pipeline["source_buckets"]:
            print("ERROR: the collector has no SOURCE_BUCKETS configured.", file=sys.stderr)
            return 1
        baseline = list_source_logs(session, pipeline["source_buckets"],
                                    pipeline["source_prefix"], today)

    client = session.client("bedrock-runtime")
    # Alternate between the two APIs so the logs contain BOTH schemas:
    # Converse (camelCase: inputTokens/stopReason) and InvokeModel (the model's
    # native format, e.g. Claude snake_case input_tokens/stop_reason). This is
    # what the dashboard view must handle via COALESCE across spellings.
    for i in range(1, args.count + 1):
        if i % 2 == 1:
            print(f"\n--- Invocation {i} [Converse] ---")
            print(invoke_converse(client, model_id, i))
        else:
            print(f"\n--- Invocation {i} [InvokeModel] ---")
            print(invoke_invoke_model(client, model_id, i))

    if not args.collect:
        print("\nDone. Check bedrock-logs-{account}-{region} for JSON.GZ log files.")
        print("Logs include both Converse and InvokeModel calls to exercise the "
              "camelCase vs native (snake_case) usage schemas.")
        print("Re-run with --collect to drive the full pipeline and verify in Athena.")
        return 0

    print("\n=== Collecting and verifying pipeline ===")
    print(f"  stack:         {pipeline['stack_name']}")
    print(f"  collector:     {pipeline['lambda_name']}")
    print(f"  source bucket: {', '.join(pipeline['source_buckets'])}")
    print(f"  destination:   {pipeline['dest_bucket']}")
    print(f"  table:         {pipeline['database']}.{pipeline['table']}")

    print(f"\nWaiting for Bedrock to deliver the new invocation log(s) for today "
          f"({today}) to S3 (up to {args.timeout}s)...")
    if not wait_for_new_source_log(session, pipeline["source_buckets"], pipeline["source_prefix"],
                                   today, baseline, timeout_s=args.timeout):
        print("ERROR: no new source log delivered within the timeout. Bedrock S3 "
              "log delivery can lag several minutes; try increasing --timeout.", file=sys.stderr)
        return 1

    print("\nRunning the collector Lambda...")
    result = run_collector(session, pipeline["lambda_name"])
    print(f"  collector result: {json.dumps(result)}")
    if result.get("errors"):
        print(f"WARNING: collector reported errors: {result['errors']}", file=sys.stderr)

    athena_output = args.athena_output or f"s3://{pipeline['dest_bucket']}/athena-results/"
    print(f"\nVerifying in Athena ({pipeline['database']}.{pipeline['table']} for {today})...")
    count = verify_athena(session, pipeline, today, athena_output)
    if count > 0:
        print(f"SUCCESS: {count} row(s) for {today} are queryable in "
              f"{pipeline['database']}.{pipeline['table']}.")
        return 0
    print(f"ERROR: no rows for {today} found in the table after collection.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
