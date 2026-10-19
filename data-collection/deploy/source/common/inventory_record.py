"""
CID Inventory Record Helpers

Generic per-resource record shaping for inventory-style collection modules:
the fields every inventory record must carry (service, resource type, id,
ARN, account, region, tags, ingest date), so each collector only has to add
the fields specific to what it collected. Takes the specific values it needs
rather than a module-specific object, so this has no dependency on any one
module and can be used by any inventory collector.
"""

from common.utils import DcUtils


def base_record(ctx, service, resource_type, resource_id, resource_arn, tags=None, region=None):
    """Build a record carrying the fields every inventory record must have.

    ``resource_name`` is deliberately not part of this base. Surveying media
    services usage across 21 call sites, a genuinely distinct name was the
    exception (5 of 21) rather than the rule — most AWS media APIs expose
    only one identifying string, which already lives in ``resource_id``.
    Add ``resource_name`` at the call site instead, alongside whatever else
    is specific to that resource, falling back to ``resource_id`` when the
    service has no independent name.

    Args:
        ctx: The collector context.
        service: Service identifier, e.g. ``"medialive"``.
        resource_type: Resource type within the service, e.g. ``"Channel"``.
        resource_id: Service-native identifier.
        resource_arn: Full ARN, used to join against CUR.
        tags: Tags as a dict or a list of ``{Key, Value}`` dicts.
        region: Override for the record's region, e.g. a bucket's location.

    Returns:
        dict: The record, ready for service-specific fields (including
        ``resource_name``) to be added.
    """
    return {
        "service": service,
        "resource_type": resource_type,
        "resource_id": resource_id or "",
        "resource_arn": resource_arn or "",
        "account_id": ctx.account_id,
        "region": region or ctx.region or "",
        "tags": DcUtils.tags_to_list(tags),
        "ingest_date": ctx.exec_ctx.ingestion_time.date().isoformat(),
    }
