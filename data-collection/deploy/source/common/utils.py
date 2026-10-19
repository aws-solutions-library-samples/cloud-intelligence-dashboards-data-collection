"""
CID Common Utilities

Shared code for CID data collection modules, packaged as the ``common``
Lambda layer. This module provides the two lightweight, dependency-free
pieces; module context/collector declarations live in ``common.context``
and the module superclass lives in ``common.module``.

``CidError`` and subclasses
    A typed error hierarchy carrying an HTTP-mapped status code, a caller
    facing message, an operator facing detail, and a fatal/non-fatal
    prognosis.

``StatusLogger``
    Builds and stores Data Collection Monitor log entries.

``DcUtils``
    Stateless helpers for cross account sessions, boto3 clients, record
    enrichment, JSONL serialization, S3 upload, and tag retrieval.  All
    methods are static, so they are callable as ``DcUtils.assume_session(...)``
    without instantiating anything.

Typical module:

    from common.context import Collector
    from common.module import DataCollectionModule

    class MediaServicesModule(DataCollectionModule):
        MODULE = "media-services"
        COLLECTORS = (
            Collector("medialive", collect_medialive),
            Collector("cloudfront", collect_cloudfront, scope=Collector.GLOBAL),
            Collector("workflow_tracing", trace_workflows, scope=Collector.DERIVED),
        )

    def lambda_handler(event, context):
        return MediaServicesModule(event, context).run()
"""

import os
import json
import uuid
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    UnknownServiceError,
)

from common.trace_logger import get_trace_logger

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
MAX_RETRIES_DEFAULT = "10"
RETRY_MODE_DEFAULT = "adaptive"
LOG_LEVEL_DEFAULT = "INFO"

TMP_DIR = "/tmp"  # nosec B108 - the only writable path in a Lambda container
TMP_FILE = "/tmp/data.json"  # nosec B108 - see TMP_DIR

# Region used for services with a single global endpoint (CloudFront, IAM, ...).
GLOBAL_REGION = "us-east-1"

# Region label applied to output that is not tied to one region.
ALL_REGIONS_LABEL = "all"

logger = logging.getLogger(__name__)


def get_logger(log_level: str = None):
    """Return the shared layer logger, configured from LOG_LEVEL.

    Args:
        log_level: Explicit level name (``TRACE``, ``DEBUG``, ``INFO``, ...).
            Falls back to the ``LOG_LEVEL`` environment variable, then to
            ``INFO``. ``TRACE`` is one level below ``DEBUG`` — see
            ``common.trace_logger``.
    """
    log = get_trace_logger(__name__)
    level = (log_level or os.environ.get("LOG_LEVEL", LOG_LEVEL_DEFAULT)).upper()
    log.setLevel(getattr(logging, level, logging.INFO))
    return log


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------
class CidError(Exception):
    """Base exception for all CID data collection errors.

    Subclasses set ``_ERR_MSG`` for the default message and ``_DEFAULT_CODE``
    for the default status code, so they need no ``__init__`` of their own.

    Args:
        code: HTTP-mapped status code. Defaults to the subclass code.
        message: Human-readable description. Defaults to ``_ERR_MSG``.
        detail: Operator-facing context (account, region, API, ...).
        prognosis: ``FATAL`` if the invocation cannot continue.
        error: The underlying exception, when wrapping one.
    """

    # Error code constants (HTTP-mapped, 400+)
    STATUS_ERR_NOT_AUTHORIZED = 401
    STATUS_ERR_FORBIDDEN = 403
    STATUS_ERR_NOT_FOUND = 404
    STATUS_ERR_NOT_ACCEPTABLE = 406
    STATUS_ERR_CONFLICT = 409
    STATUS_ERR_TOO_MANY_REQUESTS = 429
    STATUS_ERR_SERVER_ERROR = 500
    STATUS_ERR_NOT_IMPLEMENTED = 501

    FATAL = 1
    NON_FATAL = 0

    _ERR_MSG = "Unspecified CID data collection error."
    _DEFAULT_CODE = STATUS_ERR_SERVER_ERROR
    _NO_DETAIL = "no additional details"

    def __init__(self, code: int = None, message: str = None, detail: str = None,  # pylint: disable=too-many-arguments, too-many-positional-arguments
                 prognosis: int = NON_FATAL, error: Exception = None):
        self.code = code or self._DEFAULT_CODE
        self.message = message or self._ERR_MSG
        self.detail = detail or self._NO_DETAIL
        self.is_fatal = prognosis != self.NON_FATAL
        self.error = error
        self.traceback = (
            "".join(traceback.format_exception(type(error), error, error.__traceback__))
            if error is not None else traceback.format_exc()
        )
        super().__init__(str(self))
        self._log()

    def __str__(self):
        text = f"Error {self.code}: {self.message} ({self.detail})"
        if self.error is not None:
            text = f"{text} [{type(self.error).__name__}: {self.error}]"
        return text

    def _log(self):
        """Log the error at construction time, tolerating logging failures."""
        try:
            get_logger().error(str(self))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"{self} (plus logging error {exc})")


class CidAwsSessionError(CidError):
    """Raised when role assumption or session creation fails."""

    _ERR_MSG = "Unable to create an AWS session."
    _DEFAULT_CODE = CidError.STATUS_ERR_SERVER_ERROR


class CidClientConfigError(CidError):
    """Raised when a boto3 client cannot be constructed for a service/region."""

    _ERR_MSG = "Unable to create an AWS service client."
    _DEFAULT_CODE = CidError.STATUS_ERR_SERVER_ERROR


class CidInvalidRequestError(CidError):
    """Raised when the Lambda event is missing required fields or is malformed."""

    _ERR_MSG = ("Account parameters are not properly defined in the request. Please only "
                "trigger this Lambda from the corresponding StepFunction.")
    _DEFAULT_CODE = CidError.STATUS_ERR_NOT_ACCEPTABLE


class CidDataStoreError(CidError):
    """Raised when collected data cannot be stored, including S3 failures."""

    _ERR_MSG = "Unable to store the data."
    _DEFAULT_CODE = CidError.STATUS_ERR_SERVER_ERROR


# ---------------------------------------------------------------------------
# Status logging for the Data Collection Monitor dashboard
# ---------------------------------------------------------------------------
class StatusLogger:
    """Builds and stores Data Collection Monitor log entries.

    The entry schema matches the one the main state machine writes, so
    Lambda-emitted and Step Function-emitted entries share a Glue table.

    Args:
        mod_ctx: Module configuration (a ``common.context.ModuleContext``).
        exec_ctx: Per-invocation state (a ``common.context.ExecutionContext``).
    """

    # HTTP mapped success code constants
    STATUS_OKAY = 200
    STATUS_OKAY_NO_CONTENT = 204
    STATUS_MULTI_STATUS = 207

    _ERR_NOT_AUTHORIZED = "Access denied assuming or using role"
    _ERR_NOT_ACCEPTABLE = "Request is not acceptable."
    _ERR_INACTIVE_REGION = "Region might not be activated."

    def __init__(self, mod_ctx, exec_ctx):
        self.mod_ctx = mod_ctx
        self.exec_ctx = exec_ctx
        self.logger = get_logger()

    def derive_status(self, error=None, record_count=0, is_partial=False,  # pylint: disable=too-many-arguments, too-many-positional-arguments
                      status_code=None, description=""):
        """Derive a status code and description for the invocation.

        Args:
            error: Exception that ended the invocation, if any.
            record_count: Records written.
            is_partial: True when some collectors failed but others succeeded,
                which maps to ``STATUS_MULTI_STATUS``.
            status_code: Explicit override; returned unchanged when supplied.
            description: Extra text appended to the derived description.

        Returns:
            tuple: ``(status_code, description)``.
        """
        if status_code:
            return status_code, description
        if error is not None:
            return self._status_for_error(error, description)
        desc = (
            f"Execution successful: {record_count} record"
            f"{'s' if record_count != 1 else ''} found."
            f"{' ' + description if description else ''}"
        )
        if is_partial:
            return self.STATUS_MULTI_STATUS, "Partial success: " + desc
        if record_count == 0:
            return self.STATUS_OKAY_NO_CONTENT, desc
        return self.STATUS_OKAY, desc

    def _status_for_error(self, error, description=""):
        """Map an exception to a status code and description."""
        if isinstance(error, CidError):
            return error.code, str(error)
        exc_msg = str(error)
        suffix = f" {description}" if description else ""
        if "AccessDenied" in exc_msg:
            return (CidError.STATUS_ERR_NOT_AUTHORIZED,
                    f"{self._ERR_NOT_AUTHORIZED} {self.mod_ctx.role_name}. {exc_msg}{suffix}")
        if "security token included in the request is invalid" in exc_msg:
            return (CidError.STATUS_ERR_FORBIDDEN,
                    f"{type(error).__name__}: {self._ERR_INACTIVE_REGION}{suffix}")
        return (CidError.STATUS_ERR_SERVER_ERROR,
                f"{type(error).__name__}: with message {exc_msg}{suffix}")

    def create_log_entry(self, module_function: str = "data-collection-lambda", record_count: int = 0,  # pylint: disable=too-many-arguments, too-many-positional-arguments
                         error=None, is_partial: bool = False, status_code=None, sub_code: str = "",
                         location: str = None, description: str = None,
                         store_it: bool = True) -> dict:
        """Create, log, and optionally store a structured log entry.

        Args:
            module_function: Name of the function or phase being reported.
            record_count: Records written.
            error: Exception that ended the invocation, if any.
            is_partial: True when some collectors failed but others succeeded.
            status_code: Explicit status override.
            sub_code: Module-defined sub-status string.
            location: S3 URI of the output; defaults to the execution context.
            description: Extra description text.
            store_it: Write the entry to S3 when True.

        Returns:
            dict: ``{"statusCode": int, "logEntry": dict}``.
        """
        status_code, description = self.derive_status(
            error=error, record_count=record_count, is_partial=is_partial,
            status_code=status_code or self.exec_ctx.status_code,
            description=description if description is not None else self.exec_ctx.description,
        )
        location = self.exec_ctx.location if location is None else location
        log_entry = {
            "Timestamp": datetime.now(timezone.utc).isoformat(),
            "DataCollectionRegion": self._dc_region(),
            "DataCollectionAccountId": self._dc_account(),
            "Module": self.mod_ctx.module,
            "ModuleFunction": module_function,
            "Params": self.exec_ctx.params,
            "PayerId": self.exec_ctx.payer_id,
            "AccountId": self.exec_ctx.account_id or self.exec_ctx.payer_id,
            "Region": ",".join(self.exec_ctx.regions),
            "StatusCode": status_code,
            "SubCode": sub_code or self.exec_ctx.sub_code,
            "RecordCount": record_count,
            "Description": description,
            "DataLocation": location if record_count > 0 else "",
            "MainExeUuid": self.exec_ctx.main_exe_uuid,
            "SubUuid": self.exec_ctx.sub_uuid,
            "Service": "Lambda",
            "StackVersion": self.exec_ctx.stack_version,
            "SubVersion": "",
        }
        if status_code >= 400:
            self.logger.error("Result: %s", log_entry)
        else:
            self.logger.info("Result: %s", log_entry)
        if store_it:
            self._store_log_entry(log_entry)
        return {"statusCode": status_code, "logEntry": log_entry}

    @staticmethod
    def _dc_region():
        """Return the data collection account region, or an empty string."""
        try:
            return boto3.session.Session().region_name or ""
        except Exception:  # pylint: disable=broad-exception-caught
            return ""

    @staticmethod
    def _dc_account():
        """Return the data collection account id, or an empty string."""
        try:
            return boto3.client("sts").get_caller_identity()["Account"]
        except Exception:  # pylint: disable=broad-exception-caught
            return ""

    def _store_log_entry(self, log_entry):
        """Store a log entry to S3 for the Data Collection Monitor dashboard."""
        if not self.mod_ctx.bucket_name:
            self.logger.warning("No BUCKET_NAME configured, skipping log entry storage")
            return
        key = datetime.now(timezone.utc).strftime(
            f"logs/modules/%Y/%m/%d/{self.mod_ctx.module}-{uuid.uuid4()}.json"
        )
        try:
            boto3.client("s3").put_object(
                Body=json.dumps(log_entry), Bucket=self.mod_ctx.bucket_name, Key=key
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.logger.error("Error storing log entry to S3: %s", exc)


# ---------------------------------------------------------------------------
# Stateless AWS and data helpers
# ---------------------------------------------------------------------------
class DcUtils:
    """Stateless helpers for CID data collection modules.

    Every method is static, so callers use ``DcUtils.assume_session(...)``
    without instantiating the class.
    """

    # -----------------------------------------------------------------------
    # Client and session helpers
    # -----------------------------------------------------------------------
    @staticmethod
    def get_boto_config(mod_ctx) -> Config:
        """Return a botocore Config with the module's retry settings.

        Args:
            mod_ctx: Module configuration supplying max_retries and retry_mode.
        """
        return Config(retries={"max_attempts": mod_ctx.max_retries, "mode": mod_ctx.retry_mode})

    @staticmethod
    def partition_for(region) -> str:
        """Return the AWS partition for a region, defaulting to the global region.

        Args:
            region: AWS region name, or ``None``.
        """
        try:
            return boto3.session.Session().get_partition_for_region(region_name=region or GLOBAL_REGION)
        except Exception:  # pylint: disable=broad-exception-caught
            return "aws"

    @staticmethod
    def assume_session(account_id, region, role_name, mod_ctx=None):  # pylint: disable=unused-argument
        """Assume a cross-account role and return a boto3 Session.

        The role ARN is built with the partition for ``region``, so the same
        code works in ``aws``, ``aws-cn``, and ``aws-us-gov``.

        Args:
            account_id: Target AWS account id.
            region: AWS region for the STS call and partition lookup.
            role_name: IAM role name to assume in the target account.
            mod_ctx: Module configuration. Accepted for call-site symmetry.

        Returns:
            boto3.Session: Session using the assumed role credentials.

        Raises:
            CidAwsSessionError: On any credential, region, or STS failure.
        """
        try:
            partition = boto3.session.Session().get_partition_for_region(region_name=region)
            cred = boto3.client("sts", region_name=region).assume_role(
                RoleArn=f"arn:{partition}:iam::{account_id}:role/{role_name}",
                RoleSessionName="data_collection",
            )["Credentials"]
            return boto3.Session(
                aws_access_key_id=cred["AccessKeyId"],
                aws_secret_access_key=cred["SecretAccessKey"],
                aws_session_token=cred["SessionToken"],
            )
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise CidAwsSessionError(
                detail=f"Credentials error for AssumeRole in {account_id}/{region}",
                code=CidError.STATUS_ERR_NOT_AUTHORIZED, error=exc) from exc
        except NoRegionError as exc:
            raise CidAwsSessionError(
                detail=f"No region {region} for STS AssumeRole",
                code=CidError.STATUS_ERR_FORBIDDEN, error=exc) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise CidAwsSessionError(
                detail=f"Unexpected error with assume role in {account_id}/{region}",
                code=CidError.STATUS_ERR_SERVER_ERROR, error=exc) from exc

    @staticmethod
    def get_client(session, service_name, region=GLOBAL_REGION, mod_ctx=None,
                   **kwargs):
        """Create a boto3 client from a session, with typed error handling.

        Args:
            session: A boto3 Session, typically from :meth:`assume_session`.
            service_name: AWS service name, e.g. ``"medialive"``.
            region: AWS region for the client.
            mod_ctx: Module configuration supplying retry settings.
            **kwargs: Extra client arguments, e.g. ``endpoint_url``.

        Returns:
            A boto3 client for the requested service.

        Raises:
            CidClientConfigError: If the client cannot be constructed.
        """
        try:
            if mod_ctx is not None:
                kwargs.setdefault("config", DcUtils.get_boto_config(mod_ctx))
            return session.client(service_name, region_name=region, **kwargs)
        except UnknownServiceError as exc:
            raise CidClientConfigError(
                detail=f"Unknown service '{service_name}' in {region}",
                code=CidError.STATUS_ERR_NOT_IMPLEMENTED, error=exc) from exc
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise CidClientConfigError(
                detail=f"Authorization error getting client for {service_name}/{region}",
                code=CidError.STATUS_ERR_NOT_AUTHORIZED, error=exc) from exc
        except NoRegionError as exc:
            raise CidClientConfigError(
                detail=f"No region in get_client {region}",
                code=CidError.STATUS_ERR_FORBIDDEN, error=exc) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise CidClientConfigError(
                detail=f"Unexpected error in get_client {service_name}/{region}",
                code=CidError.STATUS_ERR_SERVER_ERROR, error=exc) from exc

    @staticmethod
    def get_client_for_account(service_name, account_id, region, role_name,
                               mod_ctx=None, **kwargs):
        """Assume a cross-account role and return a service client in one call.

        Args:
            service_name: AWS service name.
            account_id: Target AWS account id.
            region: AWS region for both the STS call and the client.
            role_name: IAM role name to assume in the target account.
            mod_ctx: Module configuration supplying retry settings.
            **kwargs: Extra client arguments.

        Returns:
            A boto3 client authenticated via the assumed role.

        Raises:
            CidAwsSessionError: If role assumption fails.
            CidClientConfigError: If the client cannot be constructed.
        """
        session = DcUtils.assume_session(account_id, region, role_name, mod_ctx)
        return DcUtils.get_client(session, service_name, region, mod_ctx, **kwargs)

    # -----------------------------------------------------------------------
    # Record and data handling
    # -----------------------------------------------------------------------
    @staticmethod
    def enrich_record(record: dict, payer_id: str) -> dict:
        """Add ``payer_id`` and ``collection_time`` to a record, in place.

        Args:
            record: The record to enrich.
            payer_id: Payer/management account id.

        Returns:
            dict: The same record, for convenient chaining.
        """
        record["payer_id"] = payer_id
        record["collection_time"] = datetime.now(timezone.utc).isoformat()
        return record

    @staticmethod
    def write_jsonl(records: list, tmp_file: str = TMP_FILE, append: bool = False) -> int:
        """Write records as JSON Lines to a local file.

        Truncates by default so that a warm Lambda container cannot append to
        a previous invocation's file. Pass ``append=True`` to accumulate across
        several calls.

        Args:
            records: JSON-serializable dicts to write.
            tmp_file: Destination path.
            append: Append instead of truncating.

        Returns:
            int: Number of records written.

        Raises:
            CidDataStoreError: If the file cannot be written or a record cannot
                be serialized.
        """
        count = 0
        try:
            Path(tmp_file).parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_file, "a" if append else "w", encoding="utf-8") as out:
                for record in records:
                    out.write(json.dumps(record, default=str) + "\n")
                    count += 1
            return count
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise CidDataStoreError(
                detail=f"Error storing temp data '{tmp_file}': {exc}", error=exc) from exc

    @staticmethod
    def s3_key(prefix, account_id, region, sub_name=ALL_REGIONS_LABEL):
        """Build the date-partitioned S3 key for a collection output.

        The layout is ``{prefix}-data/{sub_name}/YYYY/MM/DD/{account_id}-{region}.json``.
        Month and day are zero padded, so Glue partition projection on these
        columns must set ``projection.<col>.digits`` to ``2``.

        Args:
            prefix: Data path prefix, e.g. ``"media-services"``.
            account_id: Source account id.
            region: Source region, or ``"all"`` for cross-region output.
            sub_name: Per-collector path segment, e.g. ``"medialive"``.

        Returns:
            str: The S3 object key.
        """
        now = datetime.now(timezone.utc)
        return now.strftime(f"{prefix}-data/{sub_name}/%Y/%m/%d/{account_id}-{region}.json")

    @staticmethod
    def date_partitioned_key(prefix, sub_name, when, payer_id, account_id=None, region=None):  # pylint: disable=too-many-arguments, too-many-positional-arguments
        """Build a Hive-style, date-only partitioned S3 key.

        The layout is::

            {prefix}/{prefix}-{sub_name}-data/year=YYYY/month=MM/day=DD/
                {payer_id}[_{account_id}][_{region}]_YYYY_MM_DD.json

        Only the date is a partition, for Glue partition projection. Account
        and region go in the file name when the module writes one file per
        account and/or region, so files never collide and no extra partition
        columns are needed (CID queries filter on date, not account or region).

        Args:
            prefix: Data path prefix, e.g. ``"hello-dc"``.
            sub_name: Per-collector name, e.g. ``"sample"``.
            when: Date the data belongs to, usually the ingestion time.
            payer_id: Payer/management account id. Always in the file name.
            account_id: Source account id, for one file per account.
            region: Source region, for one file per region.

        Returns:
            str: The S3 object key.
        """
        name = "_".join(str(part) for part in (payer_id, account_id, region) if part)
        return when.strftime(
            f"{prefix}/{prefix}-{sub_name}-data/year=%Y/month=%m/day=%d/{name}_%Y_%m_%d.json")

    @staticmethod
    def upload_to_s3(tmp_file, bucket, key=None, prefix=None, account_id=None, region=None,  # pylint: disable=too-many-arguments, too-many-positional-arguments
                     sub_name=ALL_REGIONS_LABEL) -> str:
        """Upload a local file to S3.

        Supply either a fully formed ``key``, or the parts needed to build one
        via :meth:`s3_key`.

        Args:
            tmp_file: Local path of the file to upload.
            bucket: Destination bucket name.
            key: Fully formed object key. Takes precedence over the parts.
            prefix: Data path prefix used to build the key.
            account_id: Account id used to build the key.
            region: Region used to build the key.
            sub_name: Per-collector path segment used to build the key.

        Returns:
            str: The object key that was written.

        Raises:
            CidDataStoreError: If no key information is supplied, or the upload
                fails, or the local file cannot be read.
        """
        try:
            if not key and not prefix:
                raise CidDataStoreError(detail="No key information provided.")
            if not bucket:
                raise CidDataStoreError(detail="No destination bucket provided.")
            key = key or DcUtils.s3_key(prefix, account_id, region, sub_name)
            boto3.client("s3").upload_file(tmp_file, bucket, key)
            get_logger().info("Uploaded to s3://%s/%s", bucket, key)
            return key
        except ClientError as exc:
            raise CidDataStoreError(detail=f"S3 ClientError uploading to s3://{bucket}/{key}: {exc}", error=exc) from exc
        except S3UploadFailedError as exc:
            raise CidDataStoreError(detail=f"S3 upload failed for s3://{bucket}/{key}: {exc}", error=exc) from exc
        except (FileNotFoundError, OSError) as exc:
            raise CidDataStoreError(detail=f"File error reading '{tmp_file}': {exc}", error=exc) from exc

    @staticmethod
    def list_collector_keys(bucket, prefix, account_id, sub_name, date=None) -> list:
        """List this account's already-uploaded object keys for one collector.

        Args:
            bucket: Source bucket name.
            prefix: Data path prefix, e.g. ``"media-services"``.
            account_id: Source account id.
            sub_name: Per-collector path segment, e.g. ``"medialive"``.
            date: Date to look under. Defaults to today (UTC), matching
                :meth:`s3_key`.

        Returns:
            list: Matching S3 object keys, one per region that wrote output.

        Raises:
            CidDataStoreError: If the listing call fails.
        """
        date = date or datetime.now(timezone.utc)
        list_prefix = date.strftime(f"{prefix}-data/{sub_name}/%Y/%m/%d/{account_id}-")
        try:
            paginator = boto3.client("s3").get_paginator("list_objects_v2")
            return [
                obj["Key"]
                for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix)
                for obj in page.get("Contents", [])
            ]
        except ClientError as exc:
            raise CidDataStoreError(
                detail=f"S3 ClientError listing s3://{bucket}/{list_prefix}: {exc}", error=exc) from exc

    @staticmethod
    def download_jsonl(bucket, key) -> list:
        """Download and parse a JSON Lines object from S3.

        Args:
            bucket: Source bucket name.
            key: Object key.

        Returns:
            list: Parsed records.

        Raises:
            CidDataStoreError: If the object cannot be read or parsed.
        """
        try:
            body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
            return [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        except ClientError as exc:
            raise CidDataStoreError(
                detail=f"S3 ClientError reading s3://{bucket}/{key}: {exc}", error=exc) from exc

    @staticmethod
    def load_collector_records(bucket, prefix, account_id, sub_name, date=None) -> list:
        """Download and parse every already-uploaded record for one collector.

        Used to rehydrate a DERIVED collector's view of ``ctx.collected`` when
        it runs in a separate invocation from the producer collectors it
        depends on: their output already reached S3 via :meth:`upload_to_s3`,
        so this reads it back instead of re-running the producer.

        Args:
            bucket: Source bucket name.
            prefix: Data path prefix.
            account_id: Source account id.
            sub_name: Per-collector path segment whose output to load.
            date: Date to look under. Defaults to today (UTC).

        Returns:
            list: Records from every matching object, or ``[]`` if the
                collector has not written any output yet.
        """
        records = []
        for key in DcUtils.list_collector_keys(bucket, prefix, account_id, sub_name, date):
            records.extend(DcUtils.download_jsonl(bucket, key))
        return records

    @staticmethod
    def get_resource_tags(client, resource_arn) -> list:
        """Return a resource's tags as a list of ``{Key, Value}`` dicts.

        Returns an empty list when the service does not support
        ``list_tags_for_resource`` or the call fails, so callers can use the
        result unconditionally.

        Args:
            client: A boto3 client for the owning service.
            resource_arn: ARN of the resource to read tags for.

        Returns:
            list: Tag dicts, or ``[]``.
        """
        try:
            resp = client.list_tags_for_resource(ResourceArn=resource_arn)
        except Exception:  # pylint: disable=broad-exception-caught
            return []
        tags = resp.get("Tags", [])
        if isinstance(tags, dict):
            return [{"Key": key, "Value": value} for key, value in tags.items()]
        return tags

    @staticmethod
    def tags_to_list(tags) -> list:
        """Normalize a tag collection into a list of ``{Key, Value}`` dicts.

        Args:
            tags: A dict of key/value pairs, a list of tag dicts, or ``None``.

        Returns:
            list: Tag dicts, or ``[]``.
        """
        if not tags:
            return []
        if isinstance(tags, dict):
            return [{"Key": key, "Value": value} for key, value in tags.items()]
        return list(tags)

    @staticmethod
    def hostname_of(url) -> str:
        """Return the lowercase hostname of a URL, or ``""`` if it has none.

        Args:
            url: A URL or an arbitrary string.
        """
        if not url:
            return ""
        try:
            return (urlparse(str(url)).hostname or "").lower()
        except ValueError:
            return ""
