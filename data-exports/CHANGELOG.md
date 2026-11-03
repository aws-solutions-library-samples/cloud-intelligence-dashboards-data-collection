# Change Log

## v0.13.0

- Fixed `SecondaryDestinationBucket`, which stopped receiving data in v0.11.0: exports were delivered directly to the destination bucket, so nothing reached the local bucket that replicates to the secondary bucket. When `SecondaryDestinationBucket` is set, exports are again delivered to the local bucket and replicated to both the destination bucket and the secondary bucket. Without it, exports keep direct delivery.
- Restored the local bucket policy that allows AWS Data Exports to write to the local bucket (removed in v0.11.0).
- Added technical parameter `AcceptReplicationFromSources` (Destination stack, default `no`): set `yes` on destinations that receive replication from a Source stack with `SecondaryDestinationBucket` (not needed when they have `LegacyLocalBucket=yes`). Existing destinations are unchanged.
- Added `net_*` and other columns to the CUR 2.0 table definition (`line_item_net_unblended_cost`, `line_item_net_unblended_rate`, `line_item_unblended_rate`, `pricing_public_on_demand_rate`, `pricing_rate_code`, `product_region_code`, `product_sku`, `reservation_net_*`, `savings_plan_net_*` and others).
- Crawler role can create its log group by log group ARN, ahead of the CloudWatch Logs IAM change in April 2027.

Upgrade note: with `SecondaryDestinationBucket`, update both Destination stacks (destination and secondary) before the Source stack, with `AcceptReplicationFromSources=yes` unless they have `LegacyLocalBucket=yes`. Data missed by the secondary bucket since v0.11.0 is not backfilled; copy it once from the destination bucket.

## v0.12.0

- Added `EnableIAMPrincipalData` parameter (default `yes`) to include IAM principal (caller identity) data for Amazon Bedrock costs in CUR 2.0, and the `line_item_iam_principal` column.
- Data Export custom resource updates exports in place when the query changes, instead of deleting and recreating them.
- Errors on export deletion now fail the stack instead of being ignored.

## v0.11.1

- Fix for single account deployment to create Data Exports only after S3 bucket policy is created

## v0.11.0
- Added direct cross-account delivery using S3BucketOwner property — Data Exports now write directly to the destination bucket without S3 replication
- Added backward compatibility for existing deployments transitioning from S3 replication to direct delivery (LegacyLocalBucket parameter)
- Retained SecondaryDestinationBucket support for optional replication to an additional bucket
- Added metadata folder exclusion in Glue Crawlers to prevent Athena errors from manifest JSON files
- Updated CidDataExportCreatorLambda to install latest boto3 at runtime for S3BucketOwner support in non-us-east-1 regions
- Improved Lambda error handling for missing exports during Update and Delete operations
