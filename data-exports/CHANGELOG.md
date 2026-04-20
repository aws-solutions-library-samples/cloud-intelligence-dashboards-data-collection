# Change Log

## v0.11.0
- Added direct cross-account delivery using S3BucketOwner property — Data Exports now write directly to the destination bucket without S3 replication
- Added backward compatibility for existing deployments transitioning from S3 replication to direct delivery (LegacyLocalBucket parameter)
- Retained SecondaryDestinationBucket support for optional replication to an additional bucket
- Added metadata folder exclusion in Glue Crawlers to prevent Athena errors from manifest JSON files
- Updated CidDataExportCreatorLambda to install latest boto3 at runtime for S3BucketOwner support in non-us-east-1 regions
- Improved Lambda error handling for missing exports during Update and Delete operations
