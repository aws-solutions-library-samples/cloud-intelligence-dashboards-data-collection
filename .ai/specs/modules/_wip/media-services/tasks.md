# Implementation Plan: Media Services Data Collection Module

## Overview

Implement the media-services data collection module following the CID module pattern. The module collects inventory from 12 AWS media service domains via a single inline Lambda, writes per-service JSONL to S3, and exposes data through Glue tables with partition projection. Implementation builds incrementally: common layer usage, core collectors, derived collectors, CloudFormation Glue tables, wiring and integration.

**Status:** Tasks 1–7 and 12 are done for the Lambda code — the class-based common layer and all
12 collectors exist in `local-test/` and have been exercised end to end against stubbed AWS
responses (clean `200`, 60 records across 12 output files, pylint 9.97/10). Task 12 applied the
four resolved design decisions D1–D4: reference-only S3 bucket association with `s3_storage`
re-scoped to `DERIVED`, extended bucket-reference extraction, the three missing workflow edge
rules, and the new `mediapackagev2` collector.

The optional `*` property tests are still unwritten (there is no
`local-test/tests/test_module_media_services.py` yet), so the checkpoint "ensure all tests
pass" steps remain open. Tasks 8–11 (CloudFormation) have not been started.

## Progress Legend

- `[x]` = completed
- `[-]` = in progress
- `[ ]` = not started
- `[ ]*` = optional (can be skipped for faster MVP)

## Tasks

### Task 1: Refactor Lambda skeleton to use common layer and per-service output

- [x] 1.1 Build the class-based common layer and have `local-test/lambdas/module-media-services.py` use it
  - `local-test/lambdas/common/utils.py` now provides the `CidError` hierarchy, `ModuleContext` /
    `ExecutionContext` / `CollectorContext`, `StatusLogger`, `DcUtils`, the `Collector` namedtuple,
    and the `DataCollectionModule` superclass (see the Common Lambda Layer section of `design.md`)
  - The module declares `MODULE = "media-services"` and a `COLLECTORS` tuple; the superclass owns
    the region loop, session assumption, enrichment, JSONL write, S3 upload, and monitor logging.
    Collectors take a single `ctx` argument
  - Region selection, per-service S3 keys, `payer_id`/`collection_time` enrichment, and the
    `{"status": ..., "Recorded": ...}` return all live in the layer rather than the module
  - `local-test/config.json` has a `media-services` entry and `run_lambda_local.py` sends a
    state-machine-shaped event (`prefix`, `stack_version` included), so the module runs locally
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 10.3, 11.12, 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ]* 1.2 Write property test: Record enrichment (Property 5)
  - Generate random record dicts and payer_id strings, apply `enrich_record`, verify `payer_id` and `collection_time` are non-empty strings
  - **Validates:** Requirements 8.2, 10.3

- [ ]* 1.3 Write property test: JSONL round-trip (Property 6)
  - Generate random lists of dicts (string keys, JSON-serializable values), serialize as JSONL via `write_jsonl`, deserialize each line, verify equality
  - **Validates:** Requirements 8.1

- [ ]* 1.4 Write property test: S3 key path pattern (Property 7)
  - Generate random service names, account IDs, regions; call `s3_key_for_service`; verify output matches regex `media-services-data/.+/\d{4}/\d{2}/\d{2}/.+-[a-z0-9-]+\.json` and contains account_id and region
  - **Validates:** Requirements 8.3, 8.6

- [ ]* 1.5 Write property test: Region selection from event (Property 8)
  - Generate random events with and without `regions` field; verify handler uses event regions when present, falls back to env var when absent
  - **Validates:** Requirements 9.1, 9.2

- [ ]* 1.6 Write property test: Partition-aware ARN construction (Property 9)
  - Generate region strings from known partitions (us-east-1, cn-north-1, us-gov-west-1); verify `assume_session` constructs ARN with correct partition prefix
  - **Validates:** Requirements 7.2

- [ ]* 1.7 Write property test: Status response includes record count (Property 10)
  - Generate random execution scenarios (mocked collectors returning varying counts); verify return value has `status` and `Recorded` fields
  - **Validates:** Requirements 13.3

### Task 2: Implement core service collectors (MediaLive, MediaPackage, MediaConvert, MediaConnect, MediaTailor, IVS)

- [x] 2.1 Implement `collect_medialive(ctx)` with full schema
  - Paginate `list_channels` and `list_inputs`; use `describe_channel` for detailed fields (input_attachments, destinations)
  - Include all common fields: `service`, `resource_type`, `resource_id`, `resource_arn`, `resource_name`, `account_id`, `region`, `tags`
  - Include service-specific fields: `state`, `channel_class`, `input_attachments`, `destinations` for channels; `state`, `input_type`, `attached_channels` for inputs
  - Use `get_resource_tags` for tag retrieval
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 10.1, 10.2, 18.3, 18.4, 19.2, 19.3_

- [x] 2.2 Implement `collect_mediapackage(ctx)` with full schema
  - Paginate `list_channels` and `list_origin_endpoints`
  - Include common fields plus: `ingest_endpoints` for channels; `channel_id`, `startover_window_seconds`, `time_delay_seconds` for endpoints
  - Use `get_resource_tags` for tag retrieval
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 10.1, 10.2, 18.5, 18.6, 19.4, 19.5_

- [x] 2.3 Implement `collect_mediaconvert(ctx)` with full schema
  - Discover endpoint via `describe_endpoints`, then paginate `list_queues` using account-specific endpoint
  - Include common fields plus: `status`, `pricing_plan`, `reserved_slots`
  - Wrap in `try/except ClientError` returning `[]` on failure; handle endpoint discovery failure gracefully
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 10.1, 10.2, 18.7_

- [x] 2.4 Implement `collect_mediaconnect(ctx)` with full schema
  - Paginate `list_flows`
  - Include common fields plus: `status`, `availability_zone`, `source_type`
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 4.1, 4.2, 4.3, 10.1, 10.2, 18.8_

- [x] 2.5 Implement `collect_mediatailor(ctx)` with full schema
  - Paginate `list_playback_configurations`
  - Include common fields plus: `video_content_source_url`, `ad_decision_server_url`, `cdn_configuration`
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 5.1, 5.2, 5.3, 10.1, 10.2, 18.9, 19.7_

- [x] 2.6 Implement `collect_ivs(ctx)` with full schema
  - Paginate `list_channels`
  - Include common fields plus: `latency_mode`, `type`, `preset`
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 6.1, 6.2, 6.3, 10.1, 10.2, 18.10_

- [ ]* 2.7 Write property test: Common schema fields (Property 1)
  - For each of the 6 core collectors, generate random API response dicts, pass through collector with mocked boto3 client, verify output records contain all common fields
  - **Validates:** Requirements 10.1, 1.3, 1.4, 2.3, 3.3, 4.2, 5.2, 6.2

- [ ]* 2.8 Write property test: Service-specific fields (Property 2)
  - For each core collector, generate random API responses, verify service-specific fields are present
  - **Validates:** Requirements 1.3, 1.4, 2.3, 3.3, 4.2, 5.2, 6.2

- [ ]* 2.9 Write property test: Collector error resilience (Property 3)
  - For each core collector, inject `ClientError` into mocked client, verify the collector does not
    raise and returns the records it did collect — empty only when every sweep failed
  - Verify each contained failure is reported via `ctx.note_failure()`, so the run reports `207`
    rather than a silent `200`
  - **Validates:** Requirements 1.5, 2.4, 3.4, 4.3, 5.3, 6.3, 13.1

- [ ]* 2.10 Write property test: Region-level error resilience (Property 4)
  - Generate random region lists with some failing STS assume_role, verify handler completes and processes remaining regions
  - **Validates:** Requirements 7.3, 13.2

### Task 3: Checkpoint - Core collectors

- [ ] 3.1 Ensure all tests pass (`python -m pytest local-test/tests/test_module_media_services.py -v`)
  - Blocked on the test file existing; the collectors have so far been verified only by throwaway
    smoke scripts driving stubbed AWS clients
- [ ] 3.2 Ask the user if questions arise about core collector behavior

### Task 4: Implement infrastructure collectors (CloudFront, S3 Storage, CloudWatch Metrics)

- [x] 4.1 Implement `collect_cloudfront(ctx)` with full schema — declared `scope=GLOBAL`
  - Paginate `list_distributions`, call `get_distribution_config` for each
  - Include common fields plus: `domain_name`, `status`, `enabled`, `origins` (list), `cache_behaviors`, `price_class`, `associated_media_service`
  - Classify origins pointing to MediaPackage endpoints, MediaTailor configs, or media S3 buckets as media-associated
  - Note: CloudFront is a global service; collect from `us-east-1` only
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 10.1, 10.2, 18.11, 19.6_

- [x] 4.2 Implement `collect_s3_storage(ctx)` with full schema
  - Call `list_buckets`, filter to media-associated buckets by name/tag matching
  - Only buckets in the region being collected are described, so a bucket is not re-emitted once
    per region in a multi-region run
  - For each media bucket: `get_bucket_location`, `get_bucket_lifecycle_configuration`, `get_bucket_tagging`
  - Include common fields plus: `bucket_name`, `creation_date`, `lifecycle_rules`, `storage_classes`, `tags`, `associated_media_service`
  - Each bucket is swept independently, so one denial yields partial results rather than none
  - **Superseded by D1 — see Task 12.** Name-hint matching and the `REGIONAL` scope are both
    replaced; this task's output shape is no longer current.
  - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 10.1, 10.2, 19.8_

- [x] 4.3 Implement `collect_cloudwatch_metrics(ctx)` with full schema — declared `scope=DERIVED`
  - Query `get_metric_data` for MediaLive, MediaPackage, CloudFront, and S3 metrics over preceding 24-hour period
  - Reads `ctx.collected` for the resource ARNs to query metrics for, batching queries at 500 per call
  - **Judgment call to confirm:** `DERIVED` rather than `REGIONAL`, so it runs last and can cover
    the `GLOBAL` CloudFront results; its records therefore carry the `all` region label
  - Include common fields plus: `metric_namespace`, `metric_name`, `resource_arn`, `value`, `unit`, `period_start`, `period_end`, `health_indicator`, `optimization_flag`
  - Set `health_indicator` when metric values indicate unhealthy conditions
  - Set `optimization_flag` when metric values indicate cost optimization opportunities
  - Wrap in `try/except ClientError` returning `[]` on failure
  - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 10.1_

- [ ]* 4.4 Write property test: CloudFront media service association (Property 11)
  - Generate random origin domain names, verify correct `associated_media_service` classification
  - **Validates:** Requirements 15.5, 15.6

- [ ]* 4.5 Write property test: S3 bucket media association (Property 12)
  - Generate random bucket names and tags; verify correct identification of media-associated buckets
  - **Validates:** Requirements 16.6

- [ ]* 4.6 Write property test: CloudWatch metric time range (Property 13)
  - Generate random timestamps, verify query time range spans exactly 24 hours
  - **Validates:** Requirements 17.5

- [ ]* 4.7 Write property test: Health indicator and optimization flag (Property 14)
  - Generate random metric values, verify correct `health_indicator` and `optimization_flag` assignment
  - **Validates:** Requirements 17.6, 17.7

### Task 5: Checkpoint - Infrastructure collectors

- [ ] 5.1 Ensure all tests pass
- [ ] 5.2 Ask the user if questions arise

### Task 6: Implement derived collectors (Workflow Tracing, Cost Optimization)

- [x] 6.1 Implement `collect_workflow_tracing(ctx)` with full schema — declared `scope=DERIVED`
  - Build directed graph from resource relationships captured by other collectors
  - Derive `workflow_id` as the first 16 hex characters of the sha256 of the sorted connected-component ARNs
  - Output records with: common fields plus `workflow_id`, `upstream_resource_arns`, `downstream_resource_arns`, `workflow_position`
  - Handle shared resources by emitting a record per workflow
  - **Judgment call to confirm:** components of size 1 are not emitted, since a lone resource
    carries no topology
  - _Requirements: 19.1-19.12_

- [x] 6.2 Implement `collect_cost_optimization(ctx)` with full schema — declared `scope=DERIVED`
  - Analyze collected data and CloudWatch metrics to detect optimization opportunities
  - MediaConvert: flag on-demand queues with high usage, underutilized reserved queues
  - MediaConnect: flag idle flows, underutilized reserved bandwidth
  - CloudFront: flag suboptimal price class, low cache hit ratios, savings bundle eligibility
  - S3: flag missing lifecycle policies, STANDARD class without access, missing expiration rules
  - MediaLive: flag idle channels (running with zero frames), STANDARD class where SINGLE_PIPELINE suffices
  - MediaPackage: flag oversized startover windows, inactive channels
  - MediaTailor: flag unused SSAI configurations
  - Each finding includes `optimization_type` (enum) and `estimated_impact` (enum)
  - _Requirements: 20.1-20.21_

- [ ]* 6.3 Write property test: Workflow ID determinism (Property 15)
  - Generate random sets of ARN strings, compute `workflow_id` twice, verify equality
  - **Validates:** Requirements 19.9

- [ ]* 6.4 Write property test: Workflow tracing fields (Property 16)
  - Generate random workflow tracing records, verify required fields present
  - **Validates:** Requirements 19.1, 19.10

- [ ]* 6.5 Write property test: Shared resources in multiple workflows (Property 17)
  - Generate random graphs with shared nodes, verify shared resource appears in each workflow with distinct `workflow_id`
  - **Validates:** Requirements 19.12

- [ ]* 6.6 Write property test: Optimization finding schema (Property 18)
  - Generate random optimization findings, verify enum field validity
  - **Validates:** Requirements 20.19, 20.20

### Task 7: Checkpoint - Derived collectors

- [ ] 7.1 Ensure all tests pass
- [ ] 7.2 Ask the user if questions arise

### Task 12: Apply design decisions D1/D2/D4 to the collectors

> **Sequencing:** numbered 12 to avoid renumbering existing tasks, but this executes **before**
> Tasks 8–10. Those tasks lock the Glue table schemas, and everything here changes collector output
> shape. See "Design decisions (resolved 2026-09-14)" above for the reasoning behind each item.

- [x] 12.1 Re-scope `collect_s3_storage` to `DERIVED` and make association reference-only (D1)
  - Change the `COLLECTORS` entry to `Collector("s3_storage", collect_s3_storage, scope=DERIVED)`
  - **Invariant:** `s3_storage` MUST remain declared before `workflow_tracing` in `COLLECTORS`.
    `_build_resource_index` indexes buckets as `("bucket", name)` from `s3_storage` records and
    `_build_edges` consumes that, so a later declaration would silently drop every bucket edge.
    `collectors_in_scope` preserves declaration order, so position 7 vs 10 is what makes this work.
    Add a comment at the declaration and a test asserting the relative order.
  - Delete `MEDIA_BUCKET_HINTS` and the `name_match` branch of `_bucket_association`
  - Drop the `ctx.region` filter; the collector now runs once and derives each bucket's region from
    `_bucket_region()`, emitting it in the record
  - Correct the false rationale in the `collect_s3_storage` docstring
  - _Requirements: 16.1, 16.6, 16.8, 16.9_

- [x] 12.2 Extend bucket-reference extraction to all in-scope purposes (D1)
  - `_referenced_bucket_names` gains the sources below; all are free on a `list_*` call
  - MediaLive: add `Input.Sources[].Url` to `collect_medialive`'s `inputs()` sweep *(content-in)*
  - MediaPackage v1: add `list_harvest_jobs` → `S3Destination.BucketName`, `resource_type`
    `HarvestJob` *(content-out)*
  - IVS: add `list_recording_configurations` → `destinationConfiguration.s3.bucketName`,
    `resource_type` `RecordingConfiguration` *(content-out)*
  - MediaTailor: add `list_source_locations` → `HttpConfiguration.BaseUrl` and
    `DefaultSegmentDeliveryConfiguration.BaseUrl`, `resource_type` `SourceLocation` *(content-in)*
  - MediaConvert: add `list_job_templates` → `Settings.Inputs[].FileInput` and
    `OutputGroups[].*GroupSettings.Destination`, `resource_type` `JobTemplate` *(in + out)*
  - CloudFront: no new call — D1's re-scope alone makes the existing `origins[]` path live
  - New resource types land in their existing collector's table, matching how `medialive` already
    mixes `Channel` and `Input`. No new Glue tables beyond 8.14.
  - _Requirements: 1.9, 2.8, 3.7, 5.8, 6.8, 16.6, 16.7_

- [x] 12.3 Add the three missing workflow edge rules (D2)
  - IVS Channel → S3 bucket, via the recording configuration collected in 12.2
  - MediaConvert JobTemplate → Queue (`JobTemplate.Queue`) and → S3 bucket (template destinations)
  - MediaConnect Flow → MediaLive Input, via `Input.MediaConnectFlows`
  - Keep `if not edges: return []` and edge-only component construction — suppression is retained
    deliberately now that it no longer masks missing logic
  - _Requirements: 19.13, 19.14, 19.15_

- [x] 12.4 Add the `mediapackagev2` collector (D4)
  - New `Collector("mediapackagev2", collect_mediapackagev2)`, `REGIONAL`, `service` value
    `mediapackagev2` — brings the module to 12 collectors
  - Nested enumeration: `list_channel_groups` → per group `list_channels` → per channel
    `list_origin_endpoints`; all three require `ChannelGroupName`
  - `list_harvest_jobs` (per channel group) → `Destination.S3Destination.BucketName` *(content-out)*
  - Resource types: `ChannelGroup`, `Channel`, `OriginEndpoint`, `HarvestJob`
  - Each level swept independently so one denial degrades to partial results
  - **Deferred:** MediaLive→v2 topology edges need `get_channel` per channel for ingest endpoints;
    not in the MVP
  - _Requirements: 21.1-21.7_

- [x] 12.5 Correct the D3 documentation error
  - Remove any claim that metric records carry an `all` region; they carry the resource's real
    region. `all` appears only as the S3 object filename token, with no Glue-schema impact.
  - _Requirements: 17.9_

- [ ]* 12.6 Write property test: bucket association is reference-only (revised Property 12)
  - Assert no bucket is emitted without a resolvable reference from a collected resource, and that
    `associated_media_service` never takes a non-service sentinel value
  - **Validates:** Requirements 16.6, 16.8

- [ ]* 12.7 Write test: collector declaration order invariant
  - Assert `s3_storage` precedes `workflow_tracing` in `MediaServicesModule.COLLECTORS`
  - **Validates:** the 12.1 invariant

### Task 8: Define Glue tables with partition projection in CloudFormation

- [ ] 8.1 Create `data-collection/deploy/module-media-services.yaml` with no Glue Crawler
  - The template does not exist yet, so there is no `Crawler` resource to delete — simply omit one
  - Set `ModuleStepFunction.DefinitionSubstitutions.Crawlers` to the empty list `'[]'`
  - Model the template on an existing linked-account module (e.g. `module-inventory.yaml`) for the
    standard parameter set, `LambdaRole`, `LogGroup`, scheduler, and outputs
  - _Requirements: 14.8_

- [ ] 8.2 Create the deployed common layer and attach it to the Lambda
  - Create `data-collection/deploy/layers/common/` from `local-test/lambdas/common/utils.py`
    (the local copy is the working source; the two must stay in sync)
  - Add `CommonLayerArn` parameter of type String
  - Add `Layers: [!Ref CommonLayerArn]` to the `LambdaFunction` resource
  - _Requirements: 11.2, 11.11_

- [ ] 8.3 Define `MediaLiveTable` Glue table with partition projection
  - Table name: `media_services_medialive`
  - Columns matching MediaLive collector output schema (common + service-specific fields)
  - Partition keys: `year` (integer), `month` (integer), `day` (integer)
  - Partition projection enabled with `storage.location.template`, and
    `projection.month.digits: '2'` / `projection.day.digits: '2'` so the generated prefixes match
    the zero-padded S3 keys
  - SerDe: `org.openx.data.jsonserde.JsonSerDe`
  - _Requirements: 11.4, 11.5, 11.6, 14.1-14.7_

- [ ] 8.4 Define `MediaPackageTable` Glue table with partition projection
  - Table name: `media_services_mediapackage`
  - Same partition projection configuration as 8.3
  - _Requirements: 14.1-14.5_

- [ ] 8.5 Define `MediaConvertTable` Glue table with partition projection
  - Table name: `media_services_mediaconvert`
  - _Requirements: 14.1-14.5_

- [ ] 8.6 Define `MediaConnectTable` Glue table with partition projection
  - Table name: `media_services_mediaconnect`
  - _Requirements: 14.1-14.5_

- [ ] 8.7 Define `MediaTailorTable` Glue table with partition projection
  - Table name: `media_services_mediatailor`
  - _Requirements: 14.1-14.5_

- [ ] 8.8 Define `IvsTable` Glue table with partition projection
  - Table name: `media_services_ivs`
  - _Requirements: 14.1-14.5_

- [ ] 8.9 Define `CloudFrontTable` Glue table with partition projection
  - Table name: `media_services_cloudfront`
  - _Requirements: 14.1-14.5_

- [ ] 8.10 Define `S3StorageTable` Glue table with partition projection
  - Table name: `media_services_s3_storage`
  - _Requirements: 14.1-14.5_

- [ ] 8.11 Define `CloudWatchMetricsTable` Glue table with partition projection
  - Table name: `media_services_cloudwatch_metrics`
  - _Requirements: 14.1-14.5_

- [ ] 8.12 Define `WorkflowTracingTable` Glue table with partition projection
  - Table name: `media_services_workflow_tracing`
  - _Requirements: 14.1-14.5_

- [ ] 8.13 Define `CostOptimizationTable` Glue table with partition projection
  - Table name: `media_services_cost_optimization`
  - _Requirements: 14.1-14.5_

- [ ] 8.14 Define `MediaPackageV2Table` Glue table with partition projection
  - Table name: `media_services_mediapackagev2`
  - New table required by D4 — brings the module to 12 collectors / 12 tables
  - _Requirements: 21.1-21.7, 14.1-14.5_

### Task 9: Update IAM role and Lambda inline code in CloudFormation

- [ ] 9.1 Update `LambdaRole` IAM policies for all media service API permissions
  - The Lambda role only needs STS, S3, and optional KMS
  - Actual API permissions are on the cross-account role in linked accounts
  - _Requirements: 11.1, 11.9, 12.1-12.10_

- [ ] 9.2 Promote Lambda code from `local-test/lambdas/module-media-services.py` to CloudFormation `ZipFile` block
  - Replace the existing inline Python in `module-media-services.yaml` with the completed Lambda code
  - Ensure 10-space indentation for ZipFile content per CID conventions
  - Update environment variables as needed
  - _Requirements: 11.2_

### Task 10: Wire everything together and final integration

- [ ] 10.1 Update `ModuleStepFunction` DefinitionSubstitutions
  - Set `Crawlers` to `'[]'` (no crawler)
  - Verify all other substitutions are correct
  - _Requirements: 11.7_

- [ ] 10.2 Verify EventBridge scheduler configuration
  - Confirm `rate(1 day)` default schedule with 30-minute flexible time window
  - _Requirements: 11.8_

- [ ] 10.3 Verify resource naming follows `${ResourcePrefix}${CFDataName}` convention
  - Audit all resource names in the template for consistency
  - _Requirements: 11.10_

### Task 11: Final checkpoint

- [ ] 11.1 Ensure all tests pass
- [ ] 11.2 Ask the user if questions arise

## Design decisions (resolved 2026-09-14)

These were the four open judgment calls that gated the CloudFormation work, since each one changes
collector output shape and would otherwise re-lock the Glue table schemas. All are now decided.

### D1: S3 scope — reference-only, media content in/out

**Decision:** A bucket is in scope if and only if a collected media service is *configured to read
media from it or write media to it*. Name-based heuristics are removed entirely.

- `MEDIA_BUCKET_HINTS` and the `name_match` sentinel value are **deleted**. `associated_media_service`
  therefore always names a real service.
- `collect_s3_storage` moves `REGIONAL` → `DERIVED` so the reference set is complete when it runs.
- Bucket *purposes* in scope: **source/content-in** and **output/content-out**. Explicitly **out of
  scope for the MVP**: log/telemetry buckets (CloudFront `LoggingConfig.Bucket`, MediaConvert
  Kantar/Nielsen log destinations) and ancillary/metadata assets (MediaLive `ColorCorrection.Uri`,
  motion-graphics overlays, SDP locations; MediaConvert sidecar captions and image inserter;
  CloudFront CA-certificate bundles).

**Why:** the previous rationale — that generic buckets were "left to the generic inventory module" —
was factually false. No CID module collects generic S3 buckets (`module-inventory.py` covers
OpenSearch, ElastiCache, RDS, EBS, AMI, snapshots, EKS, Workspaces; `grep -rln list_buckets` hits
only this module). Nothing was being deferred *to*, so a bucket this module skipped was seen by no
module at all. A 14-substring name allow-list also silently dropped anything that did not match,
and matched things that did.

**Two defects this fixes.** Both were found by reading the code, not from the note:

1. The CloudFront reference path was **dead**. `_referenced_bucket_names` reads
   `record["origins"]`, which only `collect_cloudfront` emits — and CloudFront is `GLOBAL`, so it
   runs *after* every `REGIONAL` pass including `s3_storage`. A bucket serving as a CloudFront
   origin was only ever caught by a name-hint coincidence.
2. A **cross-region blind spot**: `collected` accumulates across regions, so a bucket in region A
   referenced only by a resource in region B was missed in both passes — not yet known during A,
   and filtered out by `_bucket_region() != ctx.region` during B.

**Accepted limitation:** buckets reached only indirectly — via a Lambda, Step Function, EC2-hosted
encoder, or ALB-fronted origin — are named in no media service API and are therefore permanently
invisible to a reference-based approach. This is a deliberate, documented gap rather than partial
coverage that reads as complete.

### D2: Workflow singletons — add missing edge rules, keep suppression

**Decision:** Keep dropping single-node components, and add the three missing edge rules.

`_build_edges` had linking logic for only four producers (MediaLive Channel, MediaPackage
OriginEndpoint, CloudFront, MediaTailor). MediaConvert, MediaConnect, and IVS had **no rules at
all**, so 100% of their resources were categorically absent from the topology table under every
circumstance — not "sometimes dropped as singletons". The suppression was hiding missing logic.

New edge rules, all built from data D1's extraction work already collects:

| Edge | Source field |
|---|---|
| IVS Channel → S3 bucket | recording configuration `destinationConfiguration.s3.bucketName` |
| MediaConvert JobTemplate → Queue, → S3 bucket | `JobTemplate.Queue`, `Settings` destinations/inputs |
| MediaConnect Flow → MediaLive Input | `Input.MediaConnectFlows` (already on `ListInputs`) |

With those in place, suppression means what it says: a resource absent from `workflow_tracing`
genuinely connects to nothing. It remains visible in its own service table and in
`cost_optimization`, so it is not invisible overall. Finding orphans is an anti-join against the
service tables rather than a `WHERE workflow_size = 1`.

**Note:** after D1, no S3 bucket can ever be isolated — a bucket is collected *because* something
references it, so it always has at least one edge.

### D3: Metrics region label — not an issue, no change

**Decision:** No code change. Correct the docs.

This was recorded as an open design question but was factually wrong. `collect_cloudwatch_metrics`
groups targets by owning region and `_metric_record` passes `region=region` into `base_record`, so
every metric row carries the resource's real region. The `all` string appears only as
`region_label` in `DataCollectionModule.emit()`, which lands in the S3 object **filename**
(`{account_id}-all.json`), not a partition path — `region` is a filename segment, not a Hive
partition directory. Zero Glue-schema impact.

### D4: MediaPackage v2 — add the sweep

**Decision:** Add a `mediapackagev2` collector. Keep the v2 resources in the fixture.

`baseline-media.yml` deploys both v1 and v2 (`MediaPackageV2::ChannelGroup/Channel/OriginEndpoint`),
but `collect_mediapackage` only ever calls the v1 API, so the v2 resources were deployed, billed,
and never collected. Resolved as a consequence of D1, since v2 harvest jobs are a content-out
bucket reference source.

**API shape note:** v2 is a three-level model and `ListChannels`, `ListOriginEndpoints`, and
`ListHarvestJobs` all **require `ChannelGroupName`**, so this is a nested enumeration
(`list_channel_groups` → per group `list_channels` → per channel `list_origin_endpoints`), not v1's
flat two calls. v2 list summaries carry no ingest endpoints (`InputType` only), so MediaLive→v2
topology linking would need `get_channel` per channel — **deferred**, noted as a gap.

### Deferred to post-MVP

Reachable by reference under D1's principle, but out of the MVP surface:

- **MediaPackage VOD** (`mediapackage-vod`) — `Asset.SourceArn` is an S3 object ARN (content-in).
- **IVS real-time** (`ivs-realtime`) — `StorageConfiguration.s3.bucketName` for composite stage
  recording (content-out).

Neither service has resources in `baseline-media.yml`, so both would also need fixture additions.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using `hypothesis` library
- Unit tests validate specific examples and edge cases
- Test file location: `local-test/tests/test_module_media_services.py`
- Run tests: `python -m pytest local-test/tests/test_module_media_services.py -v`
- Property tests that drive a whole run should go through `MediaServicesModule(event, context).run()`
  with stubbed boto3 clients, since the region loop and status logic now live in the layer
