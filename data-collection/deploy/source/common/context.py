"""
CID Module and Collector Context

Configuration and per-invocation state for CID data collection modules:

``ModuleContext`` / ``ExecutionContext``
    Configuration derived from environment variables, and per invocation
    state derived from the Step Function event.

``Collector`` / ``CollectorContext``
    The declaration type a module lists in ``COLLECTORS``, and the runtime
    object passed to a collector function for one call.
"""

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from botocore.exceptions import ClientError

from common.utils import (
    GLOBAL_REGION,
    MAX_RETRIES_DEFAULT,
    RETRY_MODE_DEFAULT,
    TMP_DIR,
    CidError,
    CidInvalidRequestError,
    DcUtils,
    get_logger,
)


# ---------------------------------------------------------------------------
# Module and execution context
# ---------------------------------------------------------------------------
def split_regions(value):
    """Normalize a region specification into a list of region names.

    Accepts a list, a comma-separated string, or ``None``.

    Args:
        value: Region list or comma-separated region string.

    Returns:
        list: Region names with surrounding whitespace and blanks removed.
    """
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = str(value).split(",")
    return [str(region).strip() for region in candidates if str(region).strip()]


class ModuleContext:  # pylint: disable=too-many-instance-attributes, too-few-public-methods
    """Module configuration read from environment variables.

    Instantiate once per invocation.  ``prefix`` is the *data path* prefix
    used to build S3 keys, which is distinct from the resource prefix the
    Step Function passes in the event.

    Args:
        prefix: Override for the ``PREFIX`` environment variable.
        module: Override for the ``MODULE`` environment variable.
        tmp_dir: Directory for intermediate JSONL files.
    """

    def __init__(self, prefix: str = None, module: str = None, tmp_dir: str = TMP_DIR):
        self.bucket_name = os.environ.get("BUCKET_NAME")
        self.prefix = prefix or os.environ.get("PREFIX", "")
        self.role_name = os.environ.get("ROLE_NAME")
        self.module = module or os.environ.get("MODULE", "")
        self.regions = split_regions(os.environ.get("REGIONS", ""))
        self.max_retries = int(os.environ.get("MAX_RETRIES", MAX_RETRIES_DEFAULT))
        self.retry_mode = os.environ.get("RETRY_MODE", RETRY_MODE_DEFAULT)
        self.tmp_dir = tmp_dir


class ExecutionContext:  # pylint: disable=too-many-instance-attributes
    """Per-invocation state derived from the Step Function event.

    The event delivered by the main state machine is::

        {"account": {...}, "params": "", "main_exe_uuid": "",
         "prefix": "", "stack_version": ""}

    ``account`` may arrive as a dict or as a JSON string depending on the
    calling state, so both are accepted.

    Args:
        event: The Lambda event.
        invocation_ctx: The Lambda context object.
        mod_ctx: Module configuration, used for the default region list.

    Raises:
        CidInvalidRequestError: If no account id can be resolved.
    """

    def __init__(self, event: dict, invocation_ctx, mod_ctx: ModuleContext):
        self.event = event or {}
        self.invocation_context = invocation_ctx
        self.main_exe_uuid = self.event.get("main_exe_uuid") or str(uuid.uuid4())
        self.stack_version = self.event.get("stack_version", "")
        self.resource_prefix = self.event.get("prefix", "")
        self.ingestion_time = self._resolve_ingestion_time(self.event.get("ingestion_time"))
        self.sub_uuid = {
            "lambda-request-id": getattr(invocation_ctx, "aws_request_id", ""),
            "lambda-log-group": getattr(invocation_ctx, "log_group_name", ""),
            "lambda-log-stream": getattr(invocation_ctx, "log_stream_name", ""),
        }
        self._status_code = None
        self._sub_code = ""
        self._location = ""
        self._description = ""
        self._record_count = 0
        try:
            self._extract_parameters(self.event, mod_ctx.regions)
        except CidInvalidRequestError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise CidInvalidRequestError(prognosis=CidError.FATAL, error=exc) from exc

    @staticmethod
    def _resolve_ingestion_time(raw):
        """Return the ingestion time as an aware datetime, defaulting to now.

        The main state machine does not send ``ingestion_time``, so absent and
        unparseable values both fall back to the current UTC time.
        """
        if raw in (None, ""):
            return datetime.now(timezone.utc)
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            return datetime.now(timezone.utc)

    def _extract_parameters(self, event: dict, default_regions):
        """Pull account, payer, regions, and params out of the event."""
        account_raw = event.get("account", "{}")
        if isinstance(account_raw, str):
            try:
                account_raw = json.loads(account_raw)
            except (json.JSONDecodeError, TypeError):
                account_raw = {}
        if not isinstance(account_raw, dict):
            account_raw = {}
        self.account_id = account_raw.get("account_id") or None
        if not self.account_id:
            raise CidInvalidRequestError(prognosis=CidError.FATAL)
        self.account_name = account_raw.get("account_name", "")
        self.payer_id = account_raw.get("payer_id") or self.account_id
        self.regions = self._resolve_regions(event, account_raw, default_regions)
        self.params = event.get("params", "")
        self.payload = event.get("payload", "")

    @staticmethod
    def _resolve_regions(event, account, default_regions):
        """Resolve the region list: event['regions'] > account['regions'] > env default."""
        regions = split_regions(event.get("regions")) or split_regions(account.get("regions"))
        return regions or split_regions(default_regions)

    @property
    def status_code(self):
        """HTTP-mapped status code for the invocation."""
        return self._status_code

    @status_code.setter
    def status_code(self, value):
        self._status_code = value

    @property
    def sub_code(self):
        """Module-defined sub-status string."""
        return self._sub_code

    @sub_code.setter
    def sub_code(self, value):
        self._sub_code = value

    @property
    def location(self):
        """S3 URI of the most recently written output."""
        return self._location

    @location.setter
    def location(self, value):
        self._location = value

    @property
    def description(self):
        """Human-readable execution summary."""
        return self._description

    @description.setter
    def description(self, value):
        self._description = value

    @property
    def record_count(self) -> int:
        """Total records written during the invocation."""
        return self._record_count

    @record_count.setter
    def record_count(self, value: int):
        self._record_count = int(value)


# ---------------------------------------------------------------------------
# Collector declaration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Collector:
    """A single unit of collection declared by a module.

    name:     path segment and Glue table suffix for the output, e.g. "medialive"
    function: callable taking a CollectorContext and returning a list of records
    scope:    Collector.REGIONAL, Collector.GLOBAL, or Collector.DERIVED
    group:    Invocation target this collector runs under, for modules split
              across multiple Lambda invocations to stay under the timeout.
              Defaults to ``name`` (one collector per invocation, like
              ``module-inventory.yaml``'s per-service Step Functions); give two
              collectors the same group to bundle lightweight services into
              one invocation, or share a group across DERIVED collectors that
              must run together and in declaration order.
    """

    # Collector scopes, controlling how often the superclass invokes a collector.
    REGIONAL = "regional"  # once per region in scope
    GLOBAL = "global"      # once, against GLOBAL_REGION (CloudFront, IAM, ...)
    DERIVED = "derived"    # once, after the others, reading ctx.collected

    name: str
    function: Callable
    scope: str = REGIONAL
    group: str = None

    def __post_init__(self):
        if self.group is None:
            object.__setattr__(self, "group", self.name)


class CollectorContext:  # pylint: disable=too-few-public-methods
    """Everything a collector needs for one call.

    Attributes:
        session: boto3 Session for the target account, or ``None`` for DERIVED.
        region: Region being collected, or ``None`` for DERIVED.
        account_id: Source account id.
        mod_ctx: Module configuration.
        exec_ctx: Per-invocation state.
        collected: Records gathered so far, keyed by collector name. DERIVED
            collectors read this; regional collectors may use it for context.
        failures: Shared list of contained failures. Collectors append to it
            via :meth:`note_failure` so partial failures reach the log entry.
    """

    def __init__(self, session, region, account_id, mod_ctx, exec_ctx, collected, failures=None):  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self.session = session
        self.region = region
        self.account_id = account_id
        self.mod_ctx = mod_ctx
        self.exec_ctx = exec_ctx
        self.collected = collected
        self.failures = failures if failures is not None else []

    def note_failure(self, label, reason):
        """Record a contained failure so it appears in the module's log entry.

        Use this for a failure the collector recovered from, such as one denied
        API call among several. The invocation still succeeds, but reports
        ``STATUS_MULTI_STATUS`` and names what was missed.

        Args:
            label: What failed, e.g. ``"medialive:inputs"``.
            reason: Why it failed.
        """
        self.failures.append((label, self.region, str(reason)))

    def sweep(self, label, func):
        """Run one API sweep, degrading to an empty list if it fails.

        Compose a collector out of independent sweeps so that a failure in
        one API call (for example ``list_inputs``) does not discard records
        another already returned (for example ``list_channels``). The
        failure is reported via :meth:`note_failure` so it reaches the Data
        Collection Monitor entry rather than only the Lambda log.

        Args:
            label: Sweep name for the log message, e.g. ``"medialive:inputs"``.
            func: Zero-argument callable performing the sweep.

        Returns:
            list: The sweep's records, or ``[]`` if it failed.
        """
        try:
            return func()
        except (ClientError, CidError) as exc:
            get_logger().warning("Sweep '%s' failed in %s/%s: %s",
                                 label, self.account_id, self.region, exc)
            self.note_failure(label, exc)
            return []
        except Exception as exc:  # pylint: disable=broad-exception-caught
            get_logger().warning("Sweep '%s' raised %s in %s/%s: %s",
                                 label, type(exc).__name__, self.account_id, self.region, exc)
            self.note_failure(label, f"{type(exc).__name__}: {exc}")
            return []

    def client(self, service_name, region=None, **kwargs):
        """Return a boto3 client for this context's session.

        Uses the given region if provided, else this context's region.
        Derived collectors have no region, so they fall back to
        :data:`GLOBAL_REGION`.

        Args:
            service_name: AWS service name.
            region: AWS region for the client. Defaults to this context's region.
            **kwargs: Extra client arguments, e.g. ``endpoint_url``.
        """
        return DcUtils.get_client(self.session, service_name, region or self.region or GLOBAL_REGION, self.mod_ctx, **kwargs)

    def all_records(self):
        """Return every record collected so far, across all collectors.

        Returns:
            list: Flattened records, in collector declaration order.
        """
        return [record for records in self.collected.values() for record in records]

    def records_for(self, collector_name) -> list:
        """Return records already collected by another collector.

        Args:
            collector_name: The other collector's declared name.

        Returns:
            list: Its records, or ``[]`` if it has not run or found nothing.
        """
        return self.collected.get(collector_name, [])
