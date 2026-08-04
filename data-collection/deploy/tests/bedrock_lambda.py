"""
Extracted Lambda source from module-bedrock.yaml ZipFile.
This module exists solely to make the Lambda functions importable by tests.
All logic is identical to the inline ZipFile code in the CloudFormation template.
"""
import os
import json
import gzip
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

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
    except botocore.exceptions.ClientError as exc:
        if exc.response['Error']['Code'] in ('NoSuchKey', 'NoSuchBucket'):
            return None
        raise
    except Exception:  #pylint: disable=broad-exception-caught
        return None


def list_s3_log_files(s3_client, source_bucket, account_id, after_dt):
    """List .json.gz log objects in the linked account's Bedrock logs bucket written after after_dt."""
    prefix = f"model-invocation-logs/AWSLogs/{account_id}/BedrockModelInvocationLogs/"
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=source_bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.endswith('.json.gz'):
                continue
            last_modified = obj['LastModified']
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            if last_modified > after_dt:
                yield key


def parse_gz_log_file(s3_client, source_bucket, key, account_id, payer_id, collection_time):
    """Download and decompress a .json.gz log file; yield one dict per line."""
    resp = s3_client.get_object(Bucket=source_bucket, Key=key)
    compressed = resp['Body'].read()
    with gzip.GzipFile(fileobj=BytesIO(compressed)) as gz:
        for raw_line in gz:
            line = raw_line.decode('utf-8').strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                record['account_id'] = account_id
                record['payer_id'] = payer_id
                record['collection_time'] = collection_time
                yield record
            except json.JSONDecodeError:
                logger.warning(f"Skipping unparseable line in {key}")


def build_s3_key(prefix, account_id, payer_id, dt):
    """Return Hive-partitioned S3 key for given UTC datetime."""
    return f"{prefix}/{prefix}-data/payer_id={payer_id}/year={dt.strftime('%Y')}/month={dt.strftime('%m')}/day={dt.strftime('%d')}/{account_id}.json"


def build_role_arn(account_id, role_name, region):
    """Return partition-aware IAM role ARN."""
    partition = boto3.session.Session().get_partition_for_region(region_name=region)
    return f"arn:{partition}:iam::{account_id}:role/{role_name}"


def store_to_s3(s3_client, records, account_id, payer_id):
    """Write records as JSONL to /tmp/data.json and upload to S3. Returns count."""
    count = 0
    with open(TMP_FILE, 'w', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')
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

    dest_s3 = boto3.client('s3')
    src_s3 = boto3.client(
        's3',
        aws_access_key_id=creds['AccessKeyId'],
        aws_secret_access_key=creds['SecretAccessKey'],
        aws_session_token=creds['SessionToken'],
    )

    source_bucket = f"bedrock-logs-{account_id}-{region}"
    now = datetime.now(tz=timezone.utc)
    last_collected = get_last_collected(dest_s3, account_id)
    after_dt = last_collected if last_collected else now - timedelta(hours=24)

    try:
        log_files = list(list_s3_log_files(src_s3, source_bucket, account_id, after_dt))
    except botocore.exceptions.ClientError as exc:
        if exc.response['Error']['Code'] in ('AccessDenied', 'AccessDeniedException', 'NoSuchBucket'):
            logger.warning(f"Cannot access source bucket in account {account_id}: {exc}")
            return
        raise

    if not log_files:
        logger.info(f"No new log files for account {account_id} since {after_dt}")
        return

    def all_records():
        for key in log_files:
            try:
                yield from parse_gz_log_file(src_s3, source_bucket, key, account_id, payer_id, collection_time)
            except Exception as exc:  #pylint: disable=broad-exception-caught
                logger.error(f"Error parsing {key}: {exc}")

    try:
        count = store_to_s3(dest_s3, all_records(), account_id, payer_id)
        if count > 0:
            update_marker(dest_s3, account_id, now)
            logger.info(f"Collection complete for account {account_id}: {count} records from {len(log_files)} files")
    except Exception as exc:  #pylint: disable=broad-exception-caught
        logger.error(f"Error storing data for account {account_id}: {exc}")
