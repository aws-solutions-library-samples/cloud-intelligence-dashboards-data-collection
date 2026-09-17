# Requirements: Media Services Data Collection Module

## Introduction

The Media Services data collection module collects inventory and operational data from AWS Media Services (MediaLive, MediaPackage, MediaConvert, MediaConnect, MediaTailor, and Interactive Video Service) and their associated infrastructure (CloudFront distributions, S3 storage locations, CloudWatch metrics and logs) across multiple linked accounts. It follows the standard CID data collection module pattern: cross-account role assumption via STS, JSONL output to S3 partitioned by service and date, Step Function orchestration, Glue table definitions with partition projection for Athena access, and daily EventBridge scheduling. The module enables cost optimization, health monitoring, misconfiguration detection, and operational visibility for media workloads across an AWS Organization.

## Glossary

| Term | Definition |
|------|------------|
| Module_Lambda | The AWS Lambda function that collects media services inventory data from linked accounts |
| Step_Function | The AWS Step Functions state machine that orchestrates account iteration and Lambda invocation |
| Collector | A Python function within the Module_Lambda responsible for gathering inventory from a single AWS media service |
| JSONL | Newline-delimited JSON format where each line is a self-contained JSON object |
| Linked_Account | An AWS account within the organization from which media services data is collected |
| Payer_Account | The management/payer account in the AWS Organization |
| Cross_Account_Role | The IAM role deployed in each linked account that the Module_Lambda assumes via STS |
| Destination_Bucket | The S3 bucket where collected JSONL data files are stored |
| Glue_Table | An AWS Glue Data Catalog table defined in CloudFormation with partition projection, enabling Athena to query collected data without a crawler |
| Partition_Projection | A Glue table configuration that automatically infers partitions from the S3 path pattern (year/month/day) without requiring a crawler or MSCK REPAIR TABLE |
| CFN_Template | The CloudFormation template that defines all module infrastructure resources |
| MediaConvert_Endpoint | The account-specific API endpoint required to interact with the MediaConvert service |
| CloudFront_Distribution | An Amazon CloudFront distribution that delivers media content, identified by association with media service origins |
| Media_S3_Bucket | An S3 bucket that a collected media service is configured to read media content from or write media content to. Identified solely by reference from a collected resource's configuration — never by bucket name or tag heuristics. See Bucket_Reference. |
| Bucket_Reference | A field in a media service API response that names an S3 bucket, either explicitly (e.g. IVS `destinationConfiguration.s3.bucketName`) or embedded in a URL or ARN (e.g. MediaLive `Destinations[].Settings[].Url` as `s3://`). Only references serving content-in or content-out purposes are in scope; log/telemetry and ancillary-asset references are not. |
| CloudWatch_Metrics | Amazon CloudWatch metrics emitted by media services and associated infrastructure |
| CloudWatch_Logs | Amazon CloudWatch log groups and log insights associated with media services |

## Requirements

### Requirement 1: MediaLive Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect MediaLive channel and input inventory across all linked accounts, so that I can track MediaLive resource usage and optimize costs.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaLive channels using paginated API calls
2. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaLive inputs using paginated API calls
3. WHEN a MediaLive channel is retrieved, THE Collector SHALL record the channel id, name, state, and channel class
4. WHEN a MediaLive input is retrieved, THE Collector SHALL record the input id, name, state, and input type
5. IF the MediaLive API returns an access error for a region, THEN THE Collector SHALL log a warning and continue processing remaining regions
6. WHEN a MediaLive channel is retrieved, THE Collector SHALL record its output destinations including `Settings[].Url`, so that `s3://` and `s3ssl://` destinations resolve as content-out Bucket_References
7. WHEN a MediaLive input is retrieved, THE Collector SHALL record its `Sources[].Url` values, so that `s3://` pull sources resolve as content-in Bucket_References
8. WHEN a MediaLive input is retrieved, THE Collector SHALL record its `MediaConnectFlows` associations, so that MediaConnect flows can be linked into the workflow graph
9. THE Collector SHALL rely only on fields present on the `list_channels` and `list_inputs` summaries, and SHALL NOT issue per-resource describe calls for Bucket_Reference extraction

### Requirement 2: MediaPackage v1 Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect MediaPackage v1 channel and origin endpoint inventory, so that I can understand packaging and origination resource deployment.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaPackage v1 channels using paginated API calls
2. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaPackage v1 origin endpoints using paginated API calls
3. WHEN a MediaPackage origin endpoint is retrieved, THE Collector SHALL record the endpoint id, description, and associated channel id
4. IF the MediaPackage API returns an access error for a region, THEN THE Collector SHALL log a warning and continue processing remaining regions
5. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaPackage v1 harvest jobs using paginated API calls
6. WHEN a harvest job is retrieved, THE Collector SHALL record it with `resource_type` `HarvestJob` including its channel id, origin endpoint id, and status
7. WHEN a harvest job is retrieved, THE Collector SHALL record `S3Destination.BucketName` as an explicit content-out Bucket_Reference
8. THE Collector SHALL treat harvest job collection as an independent sweep, so that a denial on harvest jobs does not suppress channel or origin endpoint records

### Requirement 3: MediaConvert Queue Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect MediaConvert queue inventory, so that I can track transcoding queue usage and pricing plans.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL first discover the MediaConvert_Endpoint for the account and region
2. WHEN the MediaConvert_Endpoint is discovered, THE Collector SHALL retrieve all MediaConvert queues using the account-specific endpoint
3. WHEN a MediaConvert queue is retrieved, THE Collector SHALL record the queue ARN, name, status, and pricing plan
4. IF the MediaConvert_Endpoint discovery fails, THEN THE Collector SHALL log a warning and skip MediaConvert collection for that region
5. WHEN the MediaConvert_Endpoint is discovered, THE Collector SHALL retrieve all MediaConvert job templates using the account-specific endpoint
6. WHEN a job template is retrieved, THE Collector SHALL record it with `resource_type` `JobTemplate` including its name, category, and associated queue
7. WHEN a job template is retrieved, THE Collector SHALL resolve `Settings.Inputs[].FileInput` as content-in Bucket_References and `Settings.OutputGroups[].*GroupSettings.Destination` as content-out Bucket_References
8. THE Collector SHALL NOT collect MediaConvert jobs, since jobs are transient execution records rather than persistent configuration

### Requirement 4: MediaConnect Flow Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect MediaConnect flow inventory, so that I can track live video transport resources and their configurations.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaConnect flows using paginated API calls
2. WHEN a MediaConnect flow is retrieved, THE Collector SHALL record the flow ARN, name, status, and availability zone
3. IF the MediaConnect API returns an access error for a region, THEN THE Collector SHALL log a warning and continue processing remaining regions

### Requirement 5: MediaTailor Configuration Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect MediaTailor playback configuration inventory, so that I can track server-side ad insertion deployments.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaTailor playback configurations using paginated API calls
2. WHEN a MediaTailor playback configuration is retrieved, THE Collector SHALL record the configuration name, video content source URL, ad decision server URL, and CDN configuration
3. IF the MediaTailor API returns an access error for a region, THEN THE Collector SHALL log a warning and continue processing remaining regions
4. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaTailor source locations using paginated API calls
5. WHEN a source location is retrieved, THE Collector SHALL record it with `resource_type` `SourceLocation` including its name and access type
6. WHEN a source location is retrieved, THE Collector SHALL resolve `HttpConfiguration.BaseUrl` and `DefaultSegmentDeliveryConfiguration.BaseUrl` as content-in Bucket_References where they address S3
7. THE Collector SHALL treat source location collection as an independent sweep from playback configuration collection
8. THE Collector SHALL NOT collect MediaTailor log configuration destinations, as MediaTailor logging targets CloudWatch rather than S3

### Requirement 6: Interactive Video Service (IVS) Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect IVS channel inventory, so that I can track interactive video streaming resources.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all IVS channels using paginated API calls
2. WHEN an IVS channel is retrieved, THE Collector SHALL record the channel ARN, name, latency mode, and type
3. IF the IVS API returns an access error for a region, THEN THE Collector SHALL log a warning and continue processing remaining regions
4. WHEN an IVS channel is retrieved, THE Collector SHALL record its `recordingConfigurationArn` so the channel can be joined to its recording configuration
5. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all IVS recording configurations using paginated API calls
6. WHEN a recording configuration is retrieved, THE Collector SHALL record it with `resource_type` `RecordingConfiguration` including its name and state
7. WHEN a recording configuration is retrieved, THE Collector SHALL record `destinationConfiguration.s3.bucketName` as an explicit content-out Bucket_Reference
8. THE Collector SHALL treat recording configuration collection as an independent sweep from channel collection
9. THE Collector SHALL NOT collect IVS real-time (`ivs-realtime`) stage storage configurations in the MVP; this is a documented deferred gap

### Requirement 7: Cross-Account Role Assumption

**User Story:** As a platform administrator, I want the module to assume a cross-account role in each linked account, so that data collection works across the entire AWS Organization.

**Acceptance Criteria:**

1. WHEN the Module_Lambda processes a Linked_Account, THE Module_Lambda SHALL assume the Cross_Account_Role using STS AssumeRole
2. THE Module_Lambda SHALL construct the Cross_Account_Role ARN using partition-aware formatting based on the target region
3. IF the STS AssumeRole call fails for a Linked_Account, THEN THE Module_Lambda SHALL log a warning and skip that account without failing the entire execution
4. THE Module_Lambda SHALL use the assumed session credentials for all subsequent API calls to that Linked_Account

### Requirement 8: JSONL Data Output to S3

**User Story:** As a data engineer, I want collected media services data written as JSONL to S3 with consistent partitioning, so that Athena queries can efficiently filter by payer, date, and account.

**Acceptance Criteria:**

1. THE Module_Lambda SHALL write all collected records as JSONL format with one JSON object per line
2. THE Module_Lambda SHALL include payer_id and collection_time fields in every output record
3. THE Module_Lambda SHALL write separate JSONL files per service, uploading to the Destination_Bucket using the path pattern `media-services-data/{service_name}/{YYYY}/{MM}/{DD}/{account_id}-{region}.json`
4. WHEN no media services resources are found for a Linked_Account, THE Module_Lambda SHALL log an informational message and skip the S3 upload
5. THE Module_Lambda SHALL write collected data to a temporary file in `/tmp/` before uploading to S3
6. THE JSONL file names SHALL include the account_id and region to enable identification of source without parsing file contents

### Requirement 9: Multi-Region Collection

**User Story:** As a cloud operations engineer, I want the module to collect data from all configured AWS regions, so that media services resources in any region are captured.

**Acceptance Criteria:**

1. WHEN the Linked_Account event includes a regions field, THE Module_Lambda SHALL use those regions for collection
2. WHEN the Linked_Account event does not include a regions field, THE Module_Lambda SHALL fall back to the REGIONS environment variable
3. THE Module_Lambda SHALL iterate over each region and collect data from all media service Collectors per region

### Requirement 10: Common Record Schema

**User Story:** As a data engineer, I want all media services records to share a common set of fields, so that cross-service queries and dashboards are straightforward.

**Acceptance Criteria:**

1. THE Collector SHALL include the fields service, resource_type, resource_id, resource_name, account_id, region, and tags in every output record
2. THE tags field SHALL be an array of `{Key, Value}` objects retrieved from the resource's tags where the API supports tagging; if tags are unavailable, the field SHALL be an empty array
3. THE Collector SHALL include service-specific fields as additional attributes beyond the common schema
4. THE Module_Lambda SHALL add payer_id and collection_time to each record before writing to the output file

### Requirement 11: CloudFormation Module Infrastructure

**User Story:** As a platform administrator, I want the module deployed as a standard CID CloudFormation nested stack, so that it integrates with the existing deployment pipeline.

**Acceptance Criteria:**

1. THE CFN_Template SHALL define a Lambda IAM role with least-privilege policies for STS AssumeRole, S3 PutObject, and optional KMS GenerateDataKey
2. THE CFN_Template SHALL define the Module_Lambda with inline Python code using the ZipFile property
3. THE CFN_Template SHALL define a CloudWatch log group with 60-day retention
4. THE CFN_Template SHALL define Glue_Tables (one per media service) in the Glue Data Catalog with explicit column schemas matching the JSONL output format
5. EACH Glue_Table SHALL use Partition_Projection with date-type partitions (year, month, day) mapped to the S3 path pattern `media-services-data/{service_name}/{year}/{month}/{day}/`
6. EACH Glue_Table SHALL set `projection.enabled` to `true`, `projection.year.type` to `integer`, `projection.month.type` to `integer`, `projection.day.type` to `integer`, `projection.month.digits` to `2`, `projection.day.digits` to `2`, and `storage.location.template` to the corresponding S3 path
7. THE CFN_Template SHALL define a Step_Function referencing the shared state machine template
8. THE CFN_Template SHALL define an EventBridge scheduler with a default schedule of `rate(1 day)` and a 30-minute flexible time window
9. THE CFN_Template SHALL use partition-aware ARN construction via `!Sub "arn:${AWS::Partition}:..."` for all resource ARNs
10. THE CFN_Template SHALL follow the standard resource naming convention using `${ResourcePrefix}${CFDataName}` prefix
11. THE CFN_Template SHALL accept a `CommonLayerArn` parameter and attach it to the Module_Lambda via the `Layers` property, so the Lambda imports the shared `common.utils` code rather than carrying its own copy of the framework helpers
12. THE Module_Lambda SHALL obtain its framework behavior — cross-account session assumption, region iteration, record enrichment, JSONL writing, S3 upload, Data Collection Monitor logging, and status response — from the common layer's `DataCollectionModule` superclass, and SHALL contribute only its collector functions and their declared scopes

### Requirement 12: IAM Permissions for Linked Account Role

**User Story:** As a security engineer, I want the cross-account role to have only the minimum permissions needed for media services inventory collection and associated infrastructure, so that the principle of least privilege is maintained.

**Acceptance Criteria:**

1. THE Cross_Account_Role SHALL include read-only permissions for MediaLive (medialive:ListChannels, medialive:ListInputs)
2. THE Cross_Account_Role SHALL include read-only permissions for MediaPackage (mediapackage:ListChannels, mediapackage:ListOriginEndpoints, mediapackage:ListHarvestJobs)
3. THE Cross_Account_Role SHALL include read-only permissions for MediaConvert (mediaconvert:DescribeEndpoints, mediaconvert:ListQueues, mediaconvert:ListJobTemplates)
4. THE Cross_Account_Role SHALL include read-only permissions for MediaConnect (mediaconnect:ListFlows)
5. THE Cross_Account_Role SHALL include read-only permissions for MediaTailor (mediatailor:ListPlaybackConfigurations, mediatailor:ListSourceLocations)
6. THE Cross_Account_Role SHALL include read-only permissions for IVS (ivs:ListChannels, ivs:ListRecordingConfigurations)
7. THE Cross_Account_Role SHALL include read-only permissions for CloudFront (cloudfront:ListDistributions, cloudfront:GetDistribution, cloudfront:GetDistributionConfig, cloudfront:ListCachePolicies)
8. THE Cross_Account_Role SHALL include read-only permissions for S3 (s3:ListAllMyBuckets, s3:GetBucketLocation, s3:GetBucketLifecycleConfiguration, s3:GetBucketPolicy, s3:GetBucketTagging, s3:ListBucket, s3:GetStorageClassAnalysis, s3:GetMetricsConfiguration)
9. THE Cross_Account_Role SHALL include read-only permissions for CloudWatch (cloudwatch:GetMetricData, cloudwatch:ListMetrics, logs:DescribeLogGroups, logs:FilterLogEvents, logs:GetQueryResults, logs:StartQuery)
10. THE Cross_Account_Role SHALL grant no write, modify, or delete permissions to any service
11. THE Cross_Account_Role SHALL include read-only permissions for MediaPackage v2 (mediapackagev2:ListChannelGroups, mediapackagev2:ListChannels, mediapackagev2:ListOriginEndpoints, mediapackagev2:ListHarvestJobs)

### Requirement 13: Error Handling and Resilience

**User Story:** As a platform administrator, I want the module to handle API errors gracefully without failing the entire collection run, so that partial data is still collected when individual services or regions are unavailable.

**Acceptance Criteria:**

1. IF a Collector encounters a ClientError from an AWS API, THEN THE Collector SHALL log the error as a warning and SHALL return the records it collected successfully from its other API calls, returning an empty result set only when every call failed
2. IF the STS AssumeRole call fails for a specific region, THEN THE Module_Lambda SHALL log the error and continue with the next region
3. THE Module_Lambda SHALL return a status response including the count of records collected, regardless of partial failures
4. IF the Module_Lambda is invoked without an account field in the event, THEN THE Module_Lambda SHALL raise an error with a descriptive message directing the user to the Step Function
5. IF a Collector contains a ClientError as described in 13.1, THEN THE Collector SHALL record the failure so that the run's Data Collection Monitor entry reports status `207` naming the failed calls, rather than reporting `200`

### Requirement 14: Glue Table Definitions with Partition Projection

**User Story:** As a data engineer, I want Glue tables defined in CloudFormation with partition projection on date columns, so that Athena can query collected data immediately without crawlers or manual partition repair.

**Acceptance Criteria:**

1. THE CFN_Template SHALL define one Glue_Table per media service (medialive, mediapackage, mediaconvert, mediaconnect, mediatailor, ivs, cloudfront, s3_storage, cloudwatch_metrics, workflow_tracing, cost_optimization)
2. EACH Glue_Table SHALL define an explicit column schema matching the JSONL fields output by the corresponding Collector
3. EACH Glue_Table SHALL use Partition_Projection with three integer-type partition keys: year, month, day
4. EACH Glue_Table SHALL set the `storage.location.template` property to `s3://{bucket}/media-services-data/{service_name}/{year}/{month}/{day}/`
5. EACH Glue_Table SHALL set `projection.enabled` to `true` with appropriate ranges (year: 2024 to 2040, month: 1-12, day: 1-31), and SHALL set `projection.month.digits` and `projection.day.digits` to `2` so the projected prefixes are zero-padded to match the S3 keys written by the Module_Lambda
6. EACH Glue_Table SHALL use `org.openx.data.jsonserde.JsonSerDe` as the SerDe, matching the JSONL output format
7. EACH Glue_Table SHALL be created in the Athena database specified by the DatabaseName parameter
8. THE Glue_Table definitions SHALL NOT require a Glue Crawler to discover or update partitions

### Requirement 15: CloudFront Distribution Collection

**User Story:** As a cloud operations engineer, I want to collect CloudFront distributions associated with media services, so that I can understand CDN configurations delivering media content and identify optimization opportunities.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all CloudFront distributions using paginated API calls
2. WHEN a CloudFront_Distribution is retrieved, THE Collector SHALL record the distribution id, domain name, status, enabled state, and ARN
3. WHEN a CloudFront_Distribution is retrieved, THE Collector SHALL record all origin configurations including origin id, domain name, origin path, and origin type (S3, custom, MediaPackage, MediaTailor)
4. WHEN a CloudFront_Distribution is retrieved, THE Collector SHALL record cache behavior configurations including path patterns, viewer protocol policy, and associated cache policy ids
5. THE Collector SHALL identify CloudFront_Distributions associated with media services by matching origins that point to MediaPackage endpoints, MediaTailor configurations, or Media_S3_Buckets
6. WHEN a CloudFront_Distribution has origins pointing to media service endpoints, THE Collector SHALL tag the record with the associated media service name
7. IF the CloudFront API returns an access error, THEN THE Collector SHALL log a warning and continue processing remaining services

### Requirement 16: S3 Storage Location Collection

**User Story:** As a cloud operations engineer, I want to collect S3 bucket configurations used as media storage destinations, so that I can track storage costs, lifecycle policies, and storage class usage for media workloads.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all S3 buckets and identify those that are Media_S3_Buckets
2. WHEN a Media_S3_Bucket is identified, THE Collector SHALL record the bucket name, region, and creation date
3. WHEN a Media_S3_Bucket is identified, THE Collector SHALL retrieve and record lifecycle policy rules including transition and expiration configurations
4. WHEN a Media_S3_Bucket is identified, THE Collector SHALL retrieve and record the storage classes in use
5. WHEN a Media_S3_Bucket is identified, THE Collector SHALL retrieve and record bucket tags for cost allocation context
6. THE Collector SHALL identify a Media_S3_Bucket **only** by resolving a Bucket_Reference from an already-collected media resource's configuration, covering: MediaLive channel output destinations and input sources; MediaPackage v1 and v2 harvest job destinations; MediaConvert job template inputs and output group destinations; MediaTailor source locations and content source URLs; IVS recording configuration destinations; and CloudFront S3 origins
7. THE Collector SHALL NOT identify a Media_S3_Bucket by bucket name pattern, substring hint, or tag heuristic; a bucket with no resolvable Bucket_Reference SHALL NOT be emitted
8. WHEN a Media_S3_Bucket is emitted, THE Collector SHALL record in `associated_media_service` the name of the media service whose configuration referenced it, and this value SHALL always be a real service name rather than a sentinel
9. THE Collector SHALL be declared `DERIVED` so that the reference set is complete before association is evaluated, and SHALL be declared before the workflow tracing collector so that bucket nodes are available for graph construction
10. THE Collector SHALL restrict Bucket_References to those serving media content-in or content-out purposes, and SHALL exclude log/telemetry destinations and ancillary asset references
11. IF the S3 API returns an access error for a specific bucket, THEN THE Collector SHALL log a warning and continue processing remaining buckets

### Requirement 17: CloudWatch Metrics and Logs Collection

**User Story:** As a cloud operations engineer, I want to collect CloudWatch metrics and log insights for media services, so that I can identify unhealthy resources, misconfigurations, and cost optimization opportunities.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve CloudWatch_Metrics for MediaLive channels including dropped frames, input video frame rate, output video frame rate, active alerts, and channel idle time
2. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve CloudWatch_Metrics for MediaPackage channels including ingress bytes, egress bytes, origin 4xx error count, and origin 5xx error count
3. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve CloudWatch_Metrics for CloudFront_Distributions associated with media services including total error rate, cache hit rate, bytes downloaded, and 4xx/5xx error rates
4. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve CloudWatch_Metrics for Media_S3_Buckets including number of objects, bucket size bytes, and request metrics where enabled
5. WHEN CloudWatch_Metrics are retrieved, THE Collector SHALL query metric data for the preceding 24-hour period aligned with the collection schedule
6. WHEN a metric value indicates an unhealthy condition (error rates above zero, dropped frames, idle channels), THE Collector SHALL include a health_indicator field in the output record with a descriptive status
7. WHEN a metric value indicates a cost optimization opportunity (idle channels, low cache hit ratios, missing lifecycle policies), THE Collector SHALL include an optimization_flag field in the output record
8. IF the CloudWatch API returns an access error or a metric is unavailable, THEN THE Collector SHALL log a warning and continue processing remaining metrics
9. WHEN a metric record is emitted, THE `region` field SHALL carry the owning region of the resource the metric describes, not a placeholder. The Collector groups its queries by owning region and passes that region into each record. The literal `all` appears only as the `region_label` token in the S3 object filename produced by `DataCollectionModule.emit()` (`{account_id}-all.json`), which is a filename segment rather than a Hive partition directory and therefore has no effect on Glue schemas or partition projection.

### Requirement 18: CUR Resource ID to Name Mapping

**User Story:** As a FinOps analyst, I want to join CUR line items with human-readable resource names from the collected inventory, so that cost reports show meaningful names instead of opaque resource IDs.

**Acceptance Criteria:**

1. THE Collector SHALL record both the resource_id (as it appears in CUR line_item_resource_id) and the resource_name (user-assigned name from the API) for every media service resource
2. THE Collector SHALL record the resource ARN for every media service resource to enable direct joins with CUR line_item_resource_id
3. FOR MediaLive channels, THE Collector SHALL map the channel ARN (arn:aws:medialive:*:*:channel:*) to the channel Name
4. FOR MediaLive inputs, THE Collector SHALL map the input ARN to the input Name
5. FOR MediaPackage channels, THE Collector SHALL map the channel ARN to the channel Id and Description
6. FOR MediaPackage origin endpoints, THE Collector SHALL map the endpoint ARN to the endpoint Id
7. FOR MediaConvert queues, THE Collector SHALL map the queue ARN to the queue Name
8. FOR MediaConnect flows, THE Collector SHALL map the flow ARN to the flow Name
9. FOR MediaTailor configurations, THE Collector SHALL map the configuration ARN to the configuration Name
10. FOR IVS channels, THE Collector SHALL map the channel ARN to the channel Name
11. FOR CloudFront distributions, THE Collector SHALL map the distribution ARN to the distribution Id and domain name
12. THE output schema SHALL enable an Athena JOIN between the collected data table and CUR on the resource ARN field to produce cost reports with human-readable resource names

### Requirement 19: End-to-End Media Workflow Tracing

**User Story:** As a FinOps analyst, I want to trace the end-to-end flow of configured media workflows across services, so that I can calculate the total cost of each media pipeline by joining all participating resource ARNs with CUR.

**Acceptance Criteria:**

1. THE Collector SHALL record relationship links between connected media service resources by capturing upstream and downstream resource references in each record
2. FOR MediaLive channels, THE Collector SHALL record output destination references including MediaPackage channel IDs, S3 bucket paths, and any other configured output group targets
3. FOR MediaLive channels, THE Collector SHALL record input attachment references linking to MediaLive input resource IDs
4. FOR MediaPackage channels, THE Collector SHALL record ingest endpoint URLs that link back to MediaLive output destinations
5. FOR MediaPackage origin endpoints, THE Collector SHALL record the parent channel ID to establish the channel-to-endpoint relationship
6. FOR CloudFront distributions, THE Collector SHALL record origin domain names and paths that link to MediaPackage endpoints, MediaTailor configurations, or S3 media buckets
7. FOR MediaTailor configurations, THE Collector SHALL record the video content source URL linking to the upstream MediaPackage or CloudFront origin
8. FOR S3 media buckets, THE Collector SHALL record associations with media services that write to or read from them
9. EACH output record SHALL include a workflow_id field derived from the connected resource chain, enabling grouping of all resources that participate in the same media pipeline
10. THE output schema SHALL include upstream_resource_arns and downstream_resource_arns list fields to enable graph traversal of the media workflow in Athena
11. THE workflow tracing data SHALL enable an Athena query that joins all resource ARNs in a workflow with CUR line_item_resource_id to produce a total cost per media workflow
12. IF a resource participates in multiple workflows (e.g., a shared CloudFront distribution), THE Collector SHALL include that resource in each workflow it belongs to
13. FOR IVS channels, THE Collector SHALL record the edge linking a channel to the S3 bucket named by its recording configuration
14. FOR MediaConvert job templates, THE Collector SHALL record edges linking a template to its associated queue and to the S3 buckets named by its inputs and output group destinations
15. FOR MediaConnect flows, THE Collector SHALL record the edge linking a flow to the MediaLive input that references it via `MediaConnectFlows`
16. WHEN a resource has neither an upstream nor a downstream relationship, THE Collector SHALL NOT emit a workflow tracing record for it; single-node components carry no topology information and the resource remains visible in its own service table and in cost optimization findings
17. THE absence of a resource from the workflow tracing output SHALL mean the resource genuinely connects to nothing, and SHALL NOT be an artifact of a service lacking edge-inference rules
18. THE Collector SHALL be declared after the S3 storage collector, so that bucket records are indexed and available as graph nodes when edges are built

### Requirement 20: Cost Optimization Opportunity Detection

**User Story:** As a FinOps analyst, I want the module to identify cost optimization opportunities across media services based on configurations, usage patterns, and commitment options (excluding MediaLive reservations), so that I can recommend actionable savings to stakeholders.

**Acceptance Criteria:**

**MediaConvert:**
1. THE Collector SHALL retrieve MediaConvert queue pricing plans (on-demand vs reserved) and reserved transcode slot (RTS) utilization where applicable
2. THE Collector SHALL flag on-demand queues with consistent high usage that could benefit from reserved transcode slots (up to 72% savings with 12-month commitment)
3. THE Collector SHALL flag reserved queues with low utilization where RTS commitment may be wasted
4. THE Collector SHALL capture volume-based tiered pricing eligibility by recording monthly output minutes to identify accounts approaching discount thresholds

**MediaConnect:**
5. THE Collector SHALL record MediaConnect flow running hours and data transfer volumes to identify idle or underutilized flows incurring hourly charges
6. THE Collector SHALL flag flows with reserved outbound bandwidth pricing that have low actual bandwidth utilization

**CloudFront:**
7. THE Collector SHALL record CloudFront distribution price class settings and flag distributions using PriceClass_All that could save by restricting to PriceClass_100 or PriceClass_200 based on viewer geography
8. THE Collector SHALL flag CloudFront distributions eligible for the CloudFront Security Savings Bundle (up to 30% savings with upfront commitment) based on monthly spend patterns
9. THE Collector SHALL record cache hit ratios from CloudWatch metrics and flag distributions with low cache hit rates that indicate suboptimal caching configuration

**S3 Storage:**
10. THE Collector SHALL flag Media_S3_Buckets without lifecycle policies that could benefit from automated transitions to lower-cost storage classes
11. THE Collector SHALL flag Media_S3_Buckets with objects in STANDARD storage class that have not been accessed recently and could benefit from S3 Intelligent-Tiering
12. THE Collector SHALL flag Media_S3_Buckets used for live segment output that lack expiration rules, leading to unbounded storage growth

**MediaLive (non-reservation):**
13. THE Collector SHALL use CloudWatch metrics to identify MediaLive channels in RUNNING state with zero or near-zero input/output frame rates (idle channels incurring cost)
14. THE Collector SHALL flag MediaLive channels using STANDARD (dual-pipeline) class where usage patterns suggest SINGLE_PIPELINE would suffice
15. THE Collector SHALL flag MediaLive channels with encoder settings that could be optimized (e.g., higher-than-needed resolution or bitrate for the output destination)

**MediaPackage:**
16. THE Collector SHALL record MediaPackage origin endpoint configurations and flag endpoints with startover windows or time delay settings that may be larger than needed, increasing origination costs
17. THE Collector SHALL use CloudWatch metrics to identify MediaPackage channels with zero ingress over the collection period (inactive channels)

**MediaTailor:**
18. THE Collector SHALL flag MediaTailor configurations with no ad decision server activity (zero ad impressions from CloudWatch) indicating unused SSAI configurations

**Cross-Service:**
19. EACH optimization finding SHALL include an optimization_type field categorizing the opportunity (commitment_discount, right_sizing, idle_resource, storage_tiering, configuration_tuning)
20. EACH optimization finding SHALL include an estimated_impact field with a qualitative rating (high, medium, low) based on the potential savings magnitude
21. THE output schema SHALL enable Athena queries that aggregate optimization opportunities by type, service, account, and estimated impact for reporting

### Requirement 21: MediaPackage v2 Inventory Collection

**User Story:** As a cloud operations engineer, I want to collect MediaPackage v2 inventory, so that v2 channel groups, channels, and origin endpoints are visible and billable v2 resources are not silently uncollected.

**Acceptance Criteria:**

1. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve all MediaPackage v2 channel groups using paginated API calls
2. WHEN a channel group is retrieved, THE Collector SHALL retrieve its channels, passing the required `ChannelGroupName`, and for each channel SHALL retrieve its origin endpoints, passing the required `ChannelGroupName` and `ChannelName`
3. WHEN a v2 resource is retrieved, THE Collector SHALL record it with `resource_type` `ChannelGroup`, `Channel`, or `OriginEndpoint` as appropriate, including its ARN, name, and parent names
4. WHEN the Module_Lambda is invoked for a Linked_Account, THE Collector SHALL retrieve MediaPackage v2 harvest jobs per channel group and record each with `resource_type` `HarvestJob`
5. WHEN a v2 harvest job is retrieved, THE Collector SHALL record `Destination.S3Destination.BucketName` as an explicit content-out Bucket_Reference
6. THE Collector SHALL emit records under the `mediapackagev2` service value, distinct from the v1 `mediapackage` value, so v1 and v2 occupy separate Glue tables
7. THE Collector SHALL sweep each enumeration level independently, so that a denial at one level degrades to partial results rather than suppressing the whole collector
8. THE Collector SHALL NOT issue per-channel `get_channel` calls to obtain ingest endpoints in the MVP; MediaLive-to-v2 topology edges are a documented deferred gap
