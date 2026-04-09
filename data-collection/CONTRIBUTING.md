# CONTRIBUTION GUIDE

# Development process

## Testing environment
You can test this lab in a dedicated account that preferably has the following assets:
* EC2 instances, running more than 14 days (for Compute Optimizer and CE Rightsizing)
* At least one EBS and one volume Snapshot
* At least one custom AMI created from one of the snapshots
* Activated Enterprise Support (for TA module)
* An RDS cluster or single instance
* An ECS cluster with one service deployed ([wordpress](https://aws.amazon.com/blogs/containers/running-wordpress-amazon-ecs-fargate-ecs/) will work fine)
* A TransitGateway with at least one attachment
* AWS Organization with trusted access enabled (see [Activate trusted access with AWS Organizations](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-orgs-activate-trusted-access.html))
* An S3 bucket to store the CloudFormation templates that deploy the infrastructure for the optimization data collection components

## Prerequisites for local environment

### General

* [cfn_nag_scan](https://github.com/stelligent/cfn_nag#installation)
* python3.9+
* `pip3 install -U boto3 pytest cfn-flip pylint checkov`
* Configured AWS credentials
* Install and configure [git-secrets](https://github.com/awslabs/git-secrets#installing-git-secrets)

## Testing

### AWS access credentials

For the purpose of testing, Python and shell scripts will make use of default AWS credentials setup in your ~/.aws folder.

Make sure you configure credentials for an organizations management account that will have the necessary permission to retrieve information from itself and other member accounts.

`aws configure` can be used to setup the AWS credentials in your local environment.

### Steps

1. (One time) Clone the project locally and install dependencies

```bash
git clone git@github.com:awslabs/cid-framework.git
cd cid-framework
pip3 install -U boto3 pytest cfn-flip pylint bandit cfn-lint checkov
```

Create a test bucket in test account. You can use any bucket.

```bash
export account_id=$(aws sts get-caller-identity --query "Account" --output text )
export bucket=cid-$account_id-test

aws s3api create-bucket --bucket $bucket
```

2. Check the quality of code:

Cloud Formation:
```bash
./utils/lint.sh
```

Pylint:
```bash
python3 ./utils/pylint.py
```


3. Upload the code to a bucket and run integration tests in your testing environment

```bash
./test/run-test-from-scratch.sh --no-teardown
```

The test will install stacks from scratch in a single account, then it will check the presence of Athena tables. After running tests, it will delete the stacks and all artifacts that are not deleted by CFN. You can avoid teardown by providing a flag `--no-teardown`.

To tear down all stacks and clean up without running tests:

```bash
./test/run-test-from-scratch.sh --teardown
```

To diagnose failures (check stack status, Step Function executions, Lambda errors, Glue crawlers):

```bash
./test/diagnose.sh         # last 60 minutes
./test/diagnose.sh 120     # last 2 hours
```

4. Create a merge request.


# Release process (CID Team only)
All Cloud Formation Templates are uploaded to buckets `aws-managed-cost-intelligence-dashboards*`.

```bash
./data-collection/utils/release.sh
```
