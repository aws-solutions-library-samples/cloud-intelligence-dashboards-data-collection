"""
CID Common Utilities

Shared helper functions used across multiple data collection modules.
This module is packaged as part of the CID common Lambda layer.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

MAX_RETRIES = int(os.environ.get('MAX_RETRIES', '10'))
RETRY_MODE = os.environ.get('RETRY_MODE', 'adaptive')


def get_boto_config(max_retries: int = MAX_RETRIES, mode: str = RETRY_MODE) -> Config:
    """Construct and return a botocore Config with configurable retry."""
    return Config(retries={"max_attempts": max_retries, "mode": mode})


def assume_session(account_id, region, role_name):
    """Assume a cross-account role and return a boto3 Session."""
    partition = boto3.session.Session().get_partition_for_region(region_name=region)
    cred = boto3.client('sts', region_name=region).assume_role(
        RoleArn=f"arn:{partition}:iam::{account_id}:role/{role_name}",
        RoleSessionName="data_collection"
    )['Credentials']
    return boto3.Session(
        aws_access_key_id=cred['AccessKeyId'],
        aws_secret_access_key=cred['SecretAccessKey'],
        aws_session_token=cred['SessionToken']
    )


def enrich_record(record, payer_id):
    """Add payer_id and collection_time to a record."""
    record['payer_id'] = payer_id
    record['collection_time'] = datetime.now(timezone.utc).isoformat()
    return record


def write_jsonl(records, tmp_file="/tmp/data.json"):
    """Write a list of dicts as JSONL to a temp file. Returns record count."""
    count = 0
    with open(tmp_file, "w", encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')
            count += 1
    return count


def upload_to_s3(tmp_file, bucket, key):
    """Upload a local file to S3."""
    boto3.client('s3').upload_file(tmp_file, bucket, key)
    logger.info("Uploaded to s3://%s/%s", bucket, key)


def s3_key_for_service(prefix, service_name, account_id, region):
    """Generate the S3 key path for a service collection."""
    now = datetime.now(timezone.utc)
    return now.strftime(f"{prefix}-data/{service_name}/%Y/%m/%d/{account_id}-{region}.json")


def get_resource_tags(client, resource_arn):
    """Retrieve tags for a resource ARN. Returns list of {Key, Value} dicts."""
    try:
        resp = client.list_tags_for_resource(ResourceArn=resource_arn)
        return resp.get('Tags', [])
    except (ClientError, AttributeError, Exception):  #pylint: disable=broad-exception-caught
        return []


def resolve_regions(event, account, default_regions):
    """Resolve region list: event['regions'] > account['regions'] > default."""
    event_regions = event.get("regions") or account.get("regions", "")
    if isinstance(event_regions, list):
        regions = [r.strip() for r in event_regions if r]
    else:
        regions = [r.strip() for r in str(event_regions).split(",") if r]
    return regions if regions else default_regions




# ---------------------------------------------------------------------------
# ExecutionContextUtil — structured logging for CID modules
# ---------------------------------------------------------------------------

class ExecutionContextUtil:
    """Structured logging utility for CID data collection modules.

    Constructed once at the top of lambda_handler and reused for every
    log entry during the execution.
    """

    STATUS_OKAY = 200
    STATUS_OKAY_NO_CONTENT = 204
    STATUS_MULTI_STATUS = 207
    STATUS_NOT_AUTHORIZED = 401
    STATUS_FORBIDDEN = 403
    STATUS_NOT_FOUND = 404
    STATUS_NOT_ACCEPTABLE = 406
    STATUS_CONFLICT = 409
    STATUS_TOO_MANY_REQUESTS = 429
    STATUS_SERVER_ERROR = 500
    STATUS_NOT_IMPLEMENTED = 501

    _ERR_STATUS_NOT_ACCEPTABLE = "InvocationError: Account parameters are not properly defined in request. Please only trigger this Lambda from the corresponding StepFunction."
    _ERR_STATUS_NOT_AUTHORIZED = "AccessDenied: Unable to assume role. Please make sure the role exists."

    def __init__(self, event: dict, context, module: str, bucket: str, role_name: str, log: logging.Logger = None):
        self.event = event
        self.context = context
        self.module = module
        self.bucket = bucket
        self.role_name = role_name
        self.logger = log or logging.getLogger(__name__)
        self.extract_invocation_metadata(self.event, self.context)


    def extract_invocation_metadata(self, event, context):
        """Extract execution metadata from the Step Function event.

        Populates main_exe_uuid, sub_uuid, account_id, payer_id, and params
        from the Lambda event and context.
        """
        self.main_exe_uuid = event.get("main_exe_uuid", str(uuid.uuid4()))
        self.sub_uuid = {
            "lambda-request-id": getattr(context, "aws_request_id", ""),
            "lambda-log-group": getattr(context, "log_group_name", ""),
            "lambda-log-stream": getattr(context, "log_stream_name", ""),
        }

        account_raw = event.get("account", "{}")
        if isinstance(account_raw, str):
            try:
                account_raw = json.loads(account_raw)
            except (json.JSONDecodeError, TypeError):
                account_raw = {}
        self.account_id = account_raw.get("account_id", None)
        if not self.account_id:
            logger.error(self._ERR_STATUS_NOT_ACCEPTABLE)
            raise Exception(ExecutionContextUtil.STATUS_NOT_ACCEPTABLE)  #pylint: disable=broad-exception-raised
        self.payer_id = account_raw.get("payer_id", self.account_id)
        self.regions = event.get("regions", "")
        self.params = event.get("params", "")
        self.payload = event.get("payload", "")


    def status_handler(self, error=None, record_count=0, is_summary=False,
                       status_code=None, description=""):
        """Derive status code and description. Returns (code, description)."""
        if status_code:
            return status_code, description
        if error:
            exc_msg = str(error)
            if exc_msg == str(self.STATUS_NOT_ACCEPTABLE):
                return self.STATUS_NOT_ACCEPTABLE, f"{self._ERR_STATUS_NOT_ACCEPTABLE} {' ' + description if description else ''}"
            if "AccessDenied" in exc_msg:
                return self.STATUS_NOT_AUTHORIZED, f"{self._ERR_STATUS_NOT_AUTHORIZED} ROLE {self.role_name}. {exc_msg}"
            if "security token included in the request is invalid" in exc_msg:
                return self.STATUS_FORBIDDEN, f"{type(error).__name__}: Region might not be activated."
            return self.STATUS_SERVER_ERROR, f"{type(error).__name__}: with message {exc_msg}"
        desc = (
            f"Execution successful: {record_count} record"
            f"{'s' if record_count != 1 else ''} found."
            f"{' ' + description if description else ''}"
        )
        if is_summary:
            return self.STATUS_MULTI_STATUS, "Multi-part " + desc
        if record_count == 0:
            return self.STATUS_OKAY_NO_CONTENT, desc
        return self.STATUS_OKAY, desc


    def create_log_entry(self, record_count: int = 0, location: str = "",
                         error=None, description=None, status_code=None,
                         is_summary: bool = False, store_it: bool = True,
                         module_function: str = "data-collection-lambda",
                         sub_code: str = "") -> dict:
        """Create a structured log entry and optionally store it to S3."""
        status_code, description = self.status_handler(
            error=error, record_count=record_count, is_summary=is_summary,
            status_code=status_code, description=description
        )
        dc_region = boto3.session.Session().region_name
        dc_account = boto3.client('sts').get_caller_identity()['Account']
        log_entry = {
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "DataCollectionRegion": dc_region,
            "DataCollectionAccountId": dc_account,
            "Module": self.module,
            "ModuleFunction": module_function,
            "Params": self.params,
            "PayerId": self.payer_id,
            "AccountId": self.account_id if self.account_id else self.payer_id,
            "Region": self.region,
            "StatusCode": status_code,
            "SubCode": sub_code,
            "RecordCount": record_count,
            "Description": description,
            "DataLocation": location if record_count > 0 else "",
            "MainExeUuid": self.main_exe_uuid,
            "SubUuid": self.sub_uuid,
            "Service": "Lambda"
        }
        if status_code >= 400:
            self.logger.error(description)
        if store_it:
            self._store_log_entry(log_entry)
        self.logger.info("Result: %s", log_entry)
        return {"statusCode": status_code, "logEntry": log_entry}

    def log(self, **kwargs) -> dict:
        """Alias for create_log_entry."""
        return self.create_log_entry(**kwargs)

    def _store_log_entry(self, log_entry):
        """Store a structured log entry to S3."""
        key = datetime.now(timezone.utc).strftime(
            f"logs/modules/%Y/%m/%d/{self.module}-{uuid.uuid4()}.json"
        )
        try:
            boto3.client('s3').put_object(Body=json.dumps(log_entry), Bucket=self.bucket, Key=key)
        except Exception as exc:  #pylint: disable=broad-exception-caught
            self.logger.error("Error storing log entry to S3: %s", exc)
