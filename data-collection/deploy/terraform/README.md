# Cloud Intelligence Dashboards - Terraform Deployment Solution

## Overview

This Terraform solution simplifies the deployment of data collection components for Cloud Intelligence Dashboards across AWS Organizations. It provides a streamlined approach to configure and manage data collection from multiple AWS accounts without relying on StackSets, offering better control and flexibility over the deployment process.

The solution acts as a Terraform wrapper around AWS CloudFormation templates, providing a more manageable and maintainable infrastructure-as-code approach for enterprise environments.

## Architecture

The solution consists of three main Terraform modules that work together to enable comprehensive data collection:

### 1. Management Account Module

This module configures the necessary resources in the AWS Organizations management account:

- Creates IAM roles with specific permissions for monitoring and data collection
- Enables required AWS services and APIs
- Configures access for specific features like AWS Backup, Compute Optimizer, and Cost Anomaly Detection

### 2. Linked Account Role Module

This module deploys the necessary IAM roles to each linked account for monitoring purposes:

- Creates standardized IAM roles across member accounts
- Configures granular permissions for various data collection features

### 3. Data Collection Module

This module orchestrates the data collection process and deploys CloudFormation template for data collection as a wrapper

## Version Locking

For production deployments, you should lock module versions to a release tag to better control when and what updates are made.
Use "*tag_version*" variable to select a release tag.
```bash
tag_version = "3.6.2"
```

For a complete list of release tags, visit [https://github.com/awslabs/cid-data-collection-framework/tags]https://github.com/awslabs/cid-data-collection-framework/tags.

## Deployment Process

### Step 1: Deploy Management Account Module

1. Configure your AWS credentials for the management account
2. Initialize and apply the management account module:
```bash
cd management-accounts
terraform init
terraform plan
terraform apply
```

### Step 2: Deploy Linked Account Roles

1. For each linked account:
   - Configure AWS credentials
   - Initialize and apply the linked account role module
```bash
cd linked-accounts
terraform init
terraform plan
terraform apply
```

### Step 3: Deploy Data Collection

1. Use the outputs from previous modules as inputs
2. Deploy the data collection module:
```bash
cd data-collection
terraform init
terraform plan
terraform apply
```

## Why Not StackSets?

This solution intentionally avoids using AWS StackSets for several reasons:
- Greater control over deployment timing and sequencing
- Simplified troubleshooting and rollback procedures
- Better integration with existing Terraform workflows
- More flexible permission management
- Enhanced visibility of deployment status per account

## Troubleshooting

Common issues and solutions:

1. **Linked Account Access Issues**
   - Verify IAM role trust relationships
   - Check for correct resource prefixes
   - Ensure AWS Organizations access is properly configured

2. **Permission Errors**
   - Review IAM role policies in both management and linked accounts
   - Verify service enablement in AWS Organizations
   - Check for any service quotas or limits

3. **Data Collection Failures**
   - Verify S3 bucket permissions
   - Check CloudWatch Logs for execution errors
   - Ensure correct role ARNs are being used

## Contributing

Contributions to improve the solution are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Submit a pull request with detailed description of changes
4. Ensure all existing tests pass
5. Add new tests as needed