"""
Extracted Lambda source from module-bedrock.yaml ZipFile.
This module exists solely to make the Lambda functions importable by tests.
All logic is identical to the inline ZipFile code in the CloudFormation template.
"""
import os
import json
import logging
from datetime import datetime, timedelta, timezone

import boto3
import botocore.exceptions

BUCKET_NAME = os.environ.get("BUCKET_NAME", "test-bucket")
PREFIX = os.environ.get("PREFIX", "bedrock")
ROLE_NAME = os.environ.get("ROLE_NAME", "test-role")
TMP_FILE = "/tmp/data.json"

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))


def get_last_collected(s3_client, account_id):
    """Read marker file; return datetime or None if absent/unreadable."""
    key = f"{PREFIX}/{PREFIX}-data/last_collected/{account_id}.json"
    try:
        resp = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        data = json.loads(resp['Body'].read())
        return datetime.fromisoformat(data['last_collected_timestamp'])
    except s3_client.exceptions.NoSuchKey:
        return None
    except Exception:  #pylint: disable=broad-exception-caught
        return None


def get_log_events(logs_client, log_group, start_time_ms, end_time_ms):
    """Paginate filter_log_events exhausting all nextToken pages; yield each event dict."""
    kwargs = {
        'logGroupName': log_group,
        'startTime': start_time_ms,
        'endTime': end_time_ms,
    }
    while True:
        resp = logs_client.filter_log_events(**kwargs)
        for event in resp.get('events', []):
            yield event
        next_token = resp.get('nextToken')
        if not next_token:
            break
        kwargs['nextToken'] = next_token


def build_s3_key(prefix, account_id, payer_id, dt):
    """Return Hive-partitioned S3 key for given UTC datetime."""
    return f"{prefix}/{prefix}-data/payer_id={payer_id}/year={dt.strftime('%Y')}/month={dt.strftime('%m')}/day={dt.strftime('%d')}/{account_id}.json"


def build_role_arn(account_id, role_name, region):
    """Return partition-aware IAM role ARN."""
    partition = boto3.session.Session().get_partition_for_region(region_name=region)
    return f"arn:{partition}:iam::{account_id}:role/{role_name}"


def store_to_s3(s3_client, events, account_id, payer_id, collection_time):
    """Write events as JSONL to /tmp/data.json and upload to S3. Returns count."""
    count = 0
    with open(TMP_FILE, 'w', encoding='utf-8') as f:
        for event in events:
            event['account_id'] = account_id
            event['payer_id'] = payer_id
            event['collection_time'] = collection_time
            f.write(json.dumps(event) + '\n')
            count += 1
    if count == 0:
        return 0
    key = build_s3_key(PREFIX, account_id, payer_id, datetime.now(tz=timezone.utc))
    s3_client.upload_file(TMP_FILE, BUCKET_NAME, key)
    logger.info(f"Uploaded {count} records to s3://{BUCKET_NAME}/{key}")
    return count


def update_marker(s3_client, account_id, end_time):
    """Write last_collected marker file to S3."""
    key = f"{PREFIX}/{PREFIX}-data/last_collected/{account_id}.json"
    body = json.dumps({'last_collected_timestamp': end_time.isoformat()})
    s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=body)


def lambda_handler(event, context):  #pylint: disable=W0613
    logger.info(f"Event data: {json.dumps(event)}")
    if 'account' not in event:
        raise ValueError(
            "Please do not trigger this Lambda manually. "
            "Find the corresponding state machine in Step Functions and trigger from there."
        )
    account = json.loads(event["account"])
    account_id = account["account_id"]
    payer_id = account["payer_id"]
    region = boto3.session.Session().region_name
    collection_time = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    try:
        role_arn = build_role_arn(account_id, ROLE_NAME, region)
        creds = boto3.client('sts').assume_role(
            RoleArn=role_arn,
            RoleSessionName='BedrockDataCollection'
        )['Credentials']
    except botocore.exceptions.ClientError as exc:
        if exc.response['Error']['Code'] in ('AccessDenied', 'AccessDeniedException'):
            logger.warning(f"AccessDenied assuming role in account {account_id}: {exc}")
            return
        raise

    s3_client = boto3.client('s3')
    logs_client = boto3.client(
        'logs',
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken'],
    )

    now = datetime.now(tz=timezone.utc)
    last_collected = get_last_collected(s3_client, account_id)
    start_time = last_collected if last_collected else now - timedelta(hours=24)
    end_time = now

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    try:
        events = list(get_log_events(logs_client, '/aws/bedrock/modelinvocations', start_ms, end_ms))
    except botocore.exceptions.ClientError as exc:
        if exc.response['Error']['Code'] in ('AccessDenied', 'AccessDeniedException'):
            logger.warning(f"AccessDenied reading CW Logs in account {account_id}: {exc}")
            return
        raise

    if not events:
        logger.info(f"No log events found for account {account_id} in window {start_time} to {end_time}")
        return

    try:
        count = store_to_s3(s3_client, iter(events), account_id, payer_id, collection_time)
        if count > 0:
            update_marker(s3_client, account_id, end_time)
            logger.info(f"Collection complete for account {account_id}: {count} records")
    except Exception as exc:  #pylint: disable=broad-exception-caught
        logger.error(f"Error storing data for account {account_id}: {exc}")
