"""
CID CloudWatch Metrics

Generic CloudWatch metric gathering for any resource type a module has
already collected, driven by a declarative spec map: which namespace and
dimension identify a resource, which metrics to pull, and how to classify a
value as alarm, idle, or healthy. Layered on ``CollectorContext.client``, so
any module's DERIVED collector can pull metrics for what it already found
without writing its own ``get_metric_data`` batching.

Typical use, inside a DERIVED collector so records already carry region and
identifiers to match on:

    METRIC_SPECS = {
        ("medialive", "Channel"): {
            "namespace": "AWS/MediaLive",
            "dimension": "ChannelId",
            "id_field": "resource_id",
            "metrics": [
                {"name": "ActiveAlerts", "stat": "Maximum", "alarm_above": 0},
            ],
        },
    }
    metrics = CloudWatchMetrics(METRIC_SPECS, lookback_days=1)

    def collect_cloudwatch_metrics(ctx):
        results = []
        for region, targets in metrics.group_by_region(ctx.all_records()).items():
            results.extend(sweep(ctx, f"cloudwatch:{region}",
                                  lambda r=region, t=targets: metrics.query_region(ctx, r, t)))
        return [my_record_builder(ctx, result) for result in results]

Batching and per-region grouping stay inside this class; how a result becomes
a module's own record shape (service, tags, account id, ...) stays with the
caller, along with per-region failure containment (``sweep`` above), so a
slow or denied region does not discard another region's metrics.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from common.utils import GLOBAL_REGION

# get_metric_data accepts at most 500 queries per call.
METRIC_QUERY_BATCH = 500


@dataclass(frozen=True)
class MetricResult:  # pylint: disable=too-many-instance-attributes
    """One resource/metric/window combination, aggregated and classified.

    resource:          The already-collected record the metric belongs to.
    region:            Region the metric was actually queried in. May differ
                       from ``resource["region"]`` when the spec fixes a
                       region for a global service, e.g. CloudFront.
    namespace:         CloudWatch namespace queried.
    metric_name:       CloudWatch metric name.
    value:             Aggregated value, ``0.0`` if there were no datapoints.
    unit:              The metric spec's declared unit, if any.
    datapoint_count:   Number of datapoints CloudWatch returned.
    period_start:      Window start.
    period_end:        Window end.
    health_indicator:  ``"no_data"``, ``"alarm"``, ``"idle"``, or ``"healthy"``.
    optimization_flag: True when ``health_indicator`` is ``"idle"``.
    """

    resource: dict
    region: str
    namespace: str
    metric_name: str
    value: float
    unit: str
    datapoint_count: int
    period_start: datetime
    period_end: datetime
    health_indicator: str
    optimization_flag: bool

    def metric_fields(self) -> dict:
        """Return this result's metric fields, for merging into a caller's record.

        Excludes ``resource`` and ``region`` -- the caller already has both,
        typically to build the rest of the record via its own convention
        (service, resource type, tags, ...) -- and serializes
        ``period_start``/``period_end`` to ISO strings.

        Returns:
            dict: Ready to merge with ``dict.update``.
        """
        return {
            "metric_namespace": self.namespace,
            "metric_name": self.metric_name,
            "value": self.value,
            "unit": self.unit,
            "datapoint_count": self.datapoint_count,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "health_indicator": self.health_indicator,
            "optimization_flag": self.optimization_flag,
        }


class CloudWatchMetrics:
    """Gathers CloudWatch metrics for a set of already-collected resources.

    Args:
        specs: Maps ``(service, resource_type)`` to a metric spec:
            ``namespace``, ``dimension``, ``id_field`` (the record field
            holding the dimension value), and ``metrics`` (a list of
            ``{name, stat, unit, alarm_above, idle_at_or_below}``, where
            ``alarm_above`` and ``idle_at_or_below`` are both optional).
            A spec may also set ``extra_dimensions`` (a dict of fixed
            dimension name/value pairs) and a fixed ``region`` for resources
            with a single global endpoint, e.g. CloudFront.
        lookback_days: Whole days to summarize, ending at the current hour.
    """

    def __init__(self, specs: dict, lookback_days: int = 1):
        self.specs = specs
        self.lookback_days = lookback_days

    def window(self):
        """Return the ``(start, end, period)`` CloudWatch window to summarize.

        Returns:
            tuple: Start datetime, end datetime, and period in seconds.
        """
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=max(1, self.lookback_days))
        return start, end, int((end - start).total_seconds())

    def group_by_region(self, records) -> dict:
        """Group already-collected records into per-region query targets.

        Args:
            records: Records to match against the spec map, typically
                ``ctx.all_records()``.

        Returns:
            dict: Region name to list of ``(record, spec, dimension_value)``.
        """
        grouped = {}
        for record in records:
            spec = self.specs.get((record.get("service"), record.get("resource_type")))
            if not spec:
                continue
            dimension_value = record.get(spec["id_field"], "")
            if not dimension_value:
                continue
            region = spec.get("region") or record.get("region") or GLOBAL_REGION
            grouped.setdefault(region, []).append((record, spec, dimension_value))
        return grouped

    def query_region(self, ctx, region, targets) -> list:  # pylint: disable=too-many-locals
        """Query one region's metrics for a batch of targets.

        Args:
            ctx: A collector context supplying ``client(service_name, region=...)``.
            region: Region to query.
            targets: ``(record, spec, dimension_value)`` tuples, typically from
                :meth:`group_by_region`.

        Returns:
            list: One :class:`MetricResult` per target/metric pair.
        """
        client = ctx.client("cloudwatch", region=region)
        start, end, period = self.window()
        queries, sources = self._build_queries(targets, period)
        values_by_id = {}
        for offset in range(0, len(queries), METRIC_QUERY_BATCH):
            batch = queries[offset:offset + METRIC_QUERY_BATCH]
            paginator = client.get_paginator("get_metric_data")
            for page in paginator.paginate(MetricDataQueries=batch, StartTime=start, EndTime=end):
                for result in page.get("MetricDataResults", []):
                    values_by_id.setdefault(result["Id"], []).extend(result.get("Values", []))
        return [
            self._build_result(region, source, values_by_id.get(query_id, []), start, end)
            for query_id, source in sources.items()
        ]

    @staticmethod
    def _build_queries(targets, period):
        """Build ``MetricDataQueries`` and an index back to their source resources.

        Args:
            targets: ``(record, spec, dimension_value)`` tuples.
            period: Aggregation period in seconds.

        Returns:
            tuple: ``(queries, sources)`` where sources maps query id to
            ``(record, spec, metric)``.
        """
        queries = []
        sources = {}
        for index, (record, spec, dimension_value) in enumerate(targets):
            for metric_index, metric in enumerate(spec["metrics"]):
                query_id = f"q{index}_{metric_index}"
                dimensions = [{"Name": spec["dimension"], "Value": dimension_value}]
                for name, value in spec.get("extra_dimensions", {}).items():
                    dimensions.append({"Name": name, "Value": value})
                queries.append({
                    "Id": query_id,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": spec["namespace"],
                            "MetricName": metric["name"],
                            "Dimensions": dimensions,
                        },
                        "Period": period,
                        "Stat": metric["stat"],
                    },
                    "ReturnData": True,
                })
                sources[query_id] = (record, spec, metric)
        return queries, sources

    @staticmethod
    def _build_result(region, source, values, start, end) -> MetricResult:
        """Aggregate one query's datapoints into a classified MetricResult."""
        record, spec, metric = source
        value = CloudWatchMetrics._aggregate(values, metric["stat"])
        health_indicator = CloudWatchMetrics._health_indicator(metric, value, bool(values))
        return MetricResult(
            resource=record, region=region, namespace=spec["namespace"], metric_name=metric["name"],
            value=value, unit=metric.get("unit", ""), datapoint_count=len(values),
            period_start=start, period_end=end, health_indicator=health_indicator,
            optimization_flag=health_indicator == "idle")

    @staticmethod
    def _aggregate(values, stat) -> float:
        """Reduce datapoints to a single value consistent with the statistic.

        Args:
            values: Datapoint values.
            stat: CloudWatch statistic name.

        Returns:
            float: The aggregate, or ``0.0`` when there are no datapoints.
        """
        if not values:
            return 0.0
        if stat == "Sum":
            return float(sum(values))
        if stat == "Maximum":
            return float(max(values))
        if stat == "Minimum":
            return float(min(values))
        return float(sum(values)) / len(values)

    @staticmethod
    def _health_indicator(metric, value, has_data) -> str:
        """Classify a metric value as alarm, idle, healthy, or no_data.

        Args:
            metric: The metric spec entry, carrying optional bounds.
            value: The aggregated value.
            has_data: Whether CloudWatch returned any datapoints.

        Returns:
            str: ``"no_data"``, ``"alarm"``, ``"idle"``, or ``"healthy"``.
        """
        if not has_data:
            return "no_data"
        if "alarm_above" in metric and value > metric["alarm_above"]:
            return "alarm"
        if "idle_at_or_below" in metric and value <= metric["idle_at_or_below"]:
            return "idle"
        return "healthy"
