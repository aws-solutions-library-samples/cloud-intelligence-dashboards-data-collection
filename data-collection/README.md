## CID Data Collection

### About

This projects demonstrates usage of AWS API for collecting various types of usage data.

For deployment and additional information reference to the [documentation](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html).

[![Documentation](/.images/documentation.svg)](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html)


### Architecture

![Architecture](/.images/architecture-data-collection-detailed.png)

1. [Amazon EventBridge](https://aws.amazon.com/eventbridge/) rule invokes [AWS Step Functions](https://aws.amazon.com/step-functions/) for every deployed data collection module based on schedule.
2. The Step Function launches a [AWS Lambda](https://aws.amazon.com/lambda/) function **Account Collector** that assumes **Read Role** in the Management accounts and retrieves linked accounts list via [AWS Organizations API](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_integrate_services.html).
3. Step Functions launches **Data Collection Lambda** function for each collected Account.
4. Each data collection module Lambda function assumes an [IAM](https://aws.amazon.com/iam/) role in linked accounts and retrieves respective optimization data via [AWS SDK for Python (Boto3)](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html). Retrieved data is aggregated in an [Amazon S3](https://aws.amazon.com/s3/) bucket.
5. Once data is stored in the S3 bucket, Step Functions trigger an [AWS Glue](https://aws.amazon.com/glue/) crawler which creates or updates the table in the [AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/components-overview.html#data-catalog-intro).
6. Collected data is visualized with the [Cloud Intelligence Dashboards](https://aws.amazon.com/solutions/implementations/cloud-intelligence-dashboards/) using [Amazon QuickSight](https://aws.amazon.com/quicksight/) to get optimization recommendations and insights.


### Modules
List of modules and objects collected:
| Module Name                  | AWS Services          | Collected In        | Details  |
| ---                          |  ---                  | ---                 | ---      |
| `organization`               | [AWS Organizations](https://aws.amazon.com/organizations/)     | Management Accounts  |          |
| `budgets`                    | [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/)           | Linked Accounts      |          |
| `compute-optimizer`          | [AWS Compute Optimizer](https://aws.amazon.com/compute-optimizer/) | Management Accounts  | Requires [Enablement of Compute Optimizer](https://aws.amazon.com/compute-optimizer/getting-started/#:~:text=Opt%20in%20for%20Compute%20Optimizer,created%20automatically%20in%20your%20account.) |
| `trusted-advisor`            | [AWS Trusted Advisor](https://aws.amazon.com/premiumsupport/technology/trusted-advisor/)   | Linked Accounts      | Requires Business, Enterprise or On-Ramp Support Level |
| `support-cases`              | [AWS Support](https://aws.amazon.com/premiumsupport/)           | Linked Accounts      | Requires Business, Enterprise On-Ramp, or Enterprise Support plan |
| `cost-explorer-cost-anomaly` | [AWS Cost Anomaly Detection](https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/)         | Management Accounts  |          |
| `cost-explorer-rightsizing`  | [AWS Cost Explorer](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/)     | Management Accounts  | DEPRECATED. Please use `Data Exports` for `Cost Optimization Hub` |
| `inventory`                  | Various services      | Linked Accounts      | Collects `Amazon OpenSearch Domains`, `Amazon ElastiCache Clusters`, `RDS DB Instances`, `EBS Volumes`, `AMI`, `EC2 Instances`, `EBS Snapshot`, `RDS Snapshot`, `Lambda`, `RDS DB Clusters`, `EKS Clusters` |
| `pricing`                    | Various services      | Data Collection Account | Collects pricing for `Amazon RDS`, `Amazon EC2`, `Amazon ElastiCache`, `AWS Lambda`, `Amazon OpenSearch`, `AWS Compute Savings Plan` |
| `rds-usage`                  |  [Amazon RDS](https://aws.amazon.com/rds/)           | Linked Accounts      | Collects CloudWatch metrics for chargeback |
| `transit-gateway`            |  [AWS Transit Gateway](https://aws.amazon.com/transit-gateway/)  | Linked Accounts      | Collects CloudWatch metrics for chargeback |
| `ecs-chargeback`             |  [Amazon ECS](https://aws.amazon.com/ecs/)           | Linked Accounts      |  |
| `backup`                     |  [AWS Backup](https://aws.amazon.com/backup/)           | Management Accounts  | Collects Backup Restore and Copy Jobs. Requires [activation of cross-account](https://docs.aws.amazon.com/aws-backup/latest/devguide/manage-cross-account.html#enable-cross-account) |
| `health-events`              |  [AWS Health](https://aws.amazon.com/health/) | Management Accounts  | Collect AWS Health notifications via AWS Organizational view  |
| `licence-manager`            |  [AWS License Manager](https://aws.amazon.com/license-manager/)  | Management Accounts  | Collect Licenses and Grants |
| `aws-feeds`                  |  N/A                  | Data Collection Account | Collects Blog posts and News Feeds |
| `quicksight`                 |  [Amazon QuickSight](https://aws.amazon.com/quicksight/)    | Data Collection Account | Collects QuickSight User and Group information in the Data Collection Account only |
| `resilience-hub`                 |   [AWS Resilince Hub](https://aws.amazon.com/resilience-hub/) | Linked Accounts |  |
| `agreements`                 |   [AWS Marketplace](https://aws.amazon.com/marketplace/) | Linked Accounts | Collects AWS Marketplace Agreement data and terms |
| `reference`                 |   Various services      | Data Collection Account | Collects reference data for other modules and dashboard to function |

### Deployment Overview

![Deployment Architecture](/.images/architecture-data-collection-deploy.png)

1. Deploy the Advanced Data Collection Permissions CloudFormation stack to Management (Payer) AWS Account. The Permissions CloudFormation stack in the Management (Payer) Account also deploys Permissions stacks to each of Linked accounts via StackSets.

2. Deploy the Data Collection Stack to the Data Collection AWS Account


For deployment and further information please reference to this [documentation](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html).

[![Documentation](/.images/documentation.svg)](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards/data-exports.html)


### Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md)
