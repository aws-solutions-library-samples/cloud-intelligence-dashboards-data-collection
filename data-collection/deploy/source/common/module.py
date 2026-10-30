"""
CID Data Collection Module Superclass

``DataCollectionModule`` supplies the region loop, cross-account session
handling, record enrichment, per-collector S3 upload, error containment, and
the Data Collection Monitor log entry. A module declares ``MODULE`` and
``COLLECTORS`` and the superclass runs them.
"""

import json
import os
from pathlib import Path

from botocore.exceptions import ClientError

from common.context import Collector, CollectorContext, ExecutionContext, ModuleContext
from common.utils import ALL_REGIONS_LABEL, GLOBAL_REGION, CidError, DcUtils, StatusLogger, get_logger


class DataCollectionModule:  # pylint: disable=too-many-instance-attributes
    """Superclass for CID data collection module Lambdas.

    A subclass declares ``MODULE`` and ``COLLECTORS``; this class supplies the
    region loop, cross-account sessions, per-collector error containment,
    record enrichment, per-collector S3 upload, and the Data Collection
    Monitor log entry.

    Modules whose shape differs override :meth:`collect` (the whole run) or
    :meth:`collect_region` (one region). Smaller hooks cover the common
    variations: :meth:`session_for` (which credentials), :meth:`output_key`
    (where output lands in S3), and :meth:`conform` (output record shape).

    Args:
        event: The Lambda event.
        invocation_context: The Lambda context object.

    Raises:
        CidInvalidRequestError: If the event has no resolvable account.
    """

    MODULE = ""
    COLLECTORS = ()

    def __init__(self, event: dict, invocation_context):
        self.logger = get_logger()
        self.logger.info("Event data: %s", json.dumps(event, default=str))
        self.event = event
        self.invocation_context = invocation_context
        self.mod_ctx = ModuleContext(module=self.MODULE or None)
        self.exec_ctx = ExecutionContext(event, invocation_context, self.mod_ctx)
        self.status_logger = StatusLogger(self.mod_ctx, self.exec_ctx)
        self.collected = {}
        self.failures = []

    # -----------------------------------------------------------------------
    # Subclass surface
    # -----------------------------------------------------------------------
    def collectors(self):
        """Return the collectors to run for this invocation.

        If the event's ``params`` names a :attr:`Collector.group`, only
        collectors declared with that group run, so a module can be split
        across several Lambda invocations to stay under the timeout (see
        ``module-inventory.yaml``'s per-service Step Functions for the same
        idea). An empty ``params`` runs every declared collector. Override
        for a different selection rule.
        """
        target = (self.exec_ctx.params or "").strip()
        if not target:
            return self.COLLECTORS
        return [c for c in self.COLLECTORS if c.group == target]

    def collectors_in_scope(self, scope):
        """Return declared collectors matching one scope.

        Args:
            scope: ``Collector.REGIONAL``, ``Collector.GLOBAL``, or ``Collector.DERIVED``.
        """
        return [c for c in self.collectors() if c.scope == scope]

    def session_for(self, region):
        """Return the boto3 Session collectors use in one region.

        Defaults to assuming ``ROLE_NAME`` in the event's account. Override
        to collect in the data collection account with the Lambda's own role,
        for example ``return boto3.Session()``.

        Args:
            region: Region the session is for.

        Raises:
            CidError: If no session can be created; the region is skipped.
        """
        return DcUtils.assume_session(
            self.exec_ctx.account_id, region, self.mod_ctx.role_name, self.mod_ctx)

    def output_key(self, name, region):  # pylint: disable=unused-argument
        """Return the S3 key for one collector's output, or ``None``.

        ``None`` selects the default layout from :meth:`DcUtils.s3_key`.
        Override to write a module-specific layout, such as Hive-style
        ``year=/month=/day=`` partitions for Glue partition projection.

        Args:
            name: Collector name.
            region: Source region, or ``None`` for cross-region output.
        """
        return None

    def conform(self, name, records):  # pylint: disable=unused-argument
        """Shape enriched records to the output table before they are written.

        Defaults to no change. Override to coerce records to the module's declared
        record schema, for example with :class:`common.record_schema.RecordSchema`.

        Args:
            name: Collector name.
            records: Enriched records.

        Returns:
            list: The records to write.
        """
        return records

    # -----------------------------------------------------------------------
    # Execution
    # -----------------------------------------------------------------------
    def run(self) -> dict:
        """Run the module and return the Step Function response.

        Always emits a Data Collection Monitor log entry, including on failure.
        A run in which some collectors failed and others succeeded reports
        ``STATUS_MULTI_STATUS`` and names the failures in the description.

        Returns:
            dict: ``{"status": "<code>", "Recorded": "<count>"}``.

        Raises:
            CidError: On a failure that should fail the Step Function task.
        """
        error = None
        try:
            self.collect()
        except CidError as exc:
            error = exc
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            error = exc
            raise CidError(
                message=f"Unhandled error in module '{self.mod_ctx.module}'",
                detail=str(exc), prognosis=CidError.FATAL, error=exc) from exc
        finally:
            entry = self.status_logger.create_log_entry(
                module_function="run", record_count=self.exec_ctx.record_count, error=error,
                is_partial=bool(self.failures) and error is None,
                description=self.failure_description() or None)
            self.exec_ctx.status_code = entry["statusCode"]
        return {"status": str(self.exec_ctx.status_code),
                "Recorded": str(self.exec_ctx.record_count)}

    def failure_description(self) -> str:
        """Summarize contained collector failures for the log entry.

        Returns:
            str: A description of which collectors failed where, or ``""``.
        """
        if not self.failures:
            return ""
        summary = "; ".join(
            f"{name}@{region or ALL_REGIONS_LABEL}: {reason}" for name, region, reason in self.failures)
        return f"{len(self.failures)} collector failure(s): {summary}"

    def collect(self):
        """Run every declared collector.

        Regional collectors run once per region in scope, global collectors
        once against :data:`GLOBAL_REGION`, and derived collectors last, with
        access to everything gathered before them. A region whose role
        assumption fails is skipped, not fatal.

        Derived collectors receive ``region=None`` but still get a session, so
        they can make their own calls (for example, reading CloudWatch metrics
        for resources the other collectors found).
        """
        for region in self.exec_ctx.regions:
            self.collect_region(region, self.collectors_in_scope(Collector.REGIONAL))
        if self.collectors_in_scope(Collector.GLOBAL):
            self.collect_region(GLOBAL_REGION, self.collectors_in_scope(Collector.GLOBAL))
        derived = self.collectors_in_scope(Collector.DERIVED)
        if derived:
            self.ensure_collected(c.name for c in self.COLLECTORS if c.scope != Collector.DERIVED)
            session = None
            try:
                session = self.session_for(GLOBAL_REGION)
            except CidError as exc:
                self.logger.warning("No session for derived collectors in account %s: %s",
                                    self.exec_ctx.account_id, exc)
            for collector in derived:
                self.run_collector(collector, session, None)

    def ensure_collected(self, names):
        """Backfill ``self.collected`` for producer collectors not yet in memory.

        When this invocation was scoped to a :attr:`Collector.group` that
        does not include a given producer, that producer never ran here, so
        its records are missing from ``self.collected``. Read its output back
        from S3 instead of re-running it. A no-op, with no S3 calls, for any
        name already present -- including every producer in an unscoped
        (single-invocation) run.

        Args:
            names: Producer collector names that DERIVED collectors may need.
        """
        for name in names:
            if name in self.collected:
                continue
            records = DcUtils.load_collector_records(
                self.mod_ctx.bucket_name, self.mod_ctx.prefix, self.exec_ctx.account_id, name)
            if records:
                self.collected[name] = records

    def collect_region(self, region, collectors):
        """Assume into the account for one region and run the given collectors.

        Args:
            region: Region to collect.
            collectors: Collectors to invoke for this region.
        """
        if not collectors:
            return
        try:
            session = self.session_for(region)
        except CidError as exc:
            self.logger.warning("Skipping region %s for account %s: %s",
                                region, self.exec_ctx.account_id, exc)
            self.failures.append(("<session>", region, str(exc)))
            return
        for collector in collectors:
            self.run_collector(collector, session, region)

    def run_collector(self, collector, session, region) -> int:
        """Invoke one collector and store whatever it returns.

        A collector that raises is logged and skipped, so one failing service
        never blocks the others.

        Args:
            collector: The :class:`Collector` to invoke.
            session: boto3 Session, or ``None`` for derived collectors.
            region: Region, or ``None`` for derived collectors.

        Returns:
            int: Number of records written for this collector.
        """
        ctx = CollectorContext(session, region, self.exec_ctx.account_id,
                               self.mod_ctx, self.exec_ctx, self.collected, self.failures)
        try:
            records = collector.function(ctx) or []
        except (ClientError, CidError) as exc:
            self.logger.warning("Collector '%s' failed in %s/%s: %s",
                                collector.name, self.exec_ctx.account_id, region, exc)
            self.failures.append((collector.name, region, str(exc)))
            return 0
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.logger.warning("Collector '%s' raised %s in %s/%s: %s", collector.name,
                                type(exc).__name__, self.exec_ctx.account_id, region, exc)
            self.failures.append((collector.name, region, f"{type(exc).__name__}: {exc}"))
            return 0
        if not records:
            self.logger.info("No '%s' records for %s/%s",
                             collector.name, self.exec_ctx.account_id, region)
            return 0
        self.collected.setdefault(collector.name, []).extend(records)
        return self.emit(collector.name, records, region)

    def emit(self, name, records, region) -> int:
        """Enrich, serialize, and upload one collector's records.

        Args:
            name: Collector name, used as the S3 path segment.
            records: Records to write.
            region: Source region, or ``None`` for cross-region output.

        Returns:
            int: Number of records written.
        """
        region_label = region or ALL_REGIONS_LABEL
        for record in records:
            DcUtils.enrich_record(record, self.exec_ctx.payer_id)
        records = self.conform(name, records)
        tmp_file = os.path.join(
            self.mod_ctx.tmp_dir,
            f"{self.mod_ctx.module or 'module'}-{name}-{region_label}.json")
        count = DcUtils.write_jsonl(records, tmp_file)
        key = DcUtils.upload_to_s3(
            tmp_file, self.mod_ctx.bucket_name, key=self.output_key(name, region),
            prefix=self.mod_ctx.prefix, account_id=self.exec_ctx.account_id,
            region=region_label, sub_name=name)
        self.exec_ctx.location = f"s3://{self.mod_ctx.bucket_name}/{key}"
        self.exec_ctx.record_count += count
        Path(tmp_file).unlink(missing_ok=True)
        return count
