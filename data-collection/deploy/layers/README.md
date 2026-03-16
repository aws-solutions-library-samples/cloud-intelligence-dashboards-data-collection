# Lambda Layer Usage Guide

## Overview

This directory contains Lambda layers that can be used across all data collection modules. The primary layer is the Boto3 layer, which provides the latest boto3 and botocore libraries.

## Boto3 Layer

### Building the Layer Locally

To build the Boto3 layer locally for testing:

```bash
cd data-collection/deploy/layers
./build-boto3-layer.sh
```

This creates `boto3-layer.zip` in the same directory with:
- Latest boto3 library
- Latest botocore library
- Version-agnostic structure (compatible with all Python 3.x runtimes)

**Note**: The zip file is NOT committed to the repository. It's built during the release process.

### Publishing the Layer (Release Process)

The layer is automatically built and published to all regional S3 buckets during the release process:

```bash
cd data-collection/deploy/layers
./publish-boto3-layer.sh
```

This script:
1. Builds the layer using `build-boto3-layer.sh`
2. Uploads to the central bucket: `aws-managed-cost-intelligence-dashboards`
3. Uploads to all regional buckets in the LayerBuckets StackSet
4. Uses the version from `data-collection/utils/version.json`
5. Cleans up the local zip file

**Prerequisites for publishing**:
- AWS CLI configured with appropriate credentials
- LayerBuckets CloudFormation StackSet deployed
- Access to the central and regional buckets

### Layer Structure

The layer uses a simplified, version-agnostic structure:

```
boto3-layer.zip
└── python/
    ├── boto3/
    ├── botocore/
    └── [dependencies]
```

This structure works with all Python 3.x Lambda runtimes (3.9, 3.10, 3.11, 3.12, 3.13) without rebuilding.

### CloudFormation Definition

The layer is defined in `deploy-data-collection.yaml`:

```yaml
Boto3LayerVersion:
  Type: AWS::Lambda::LayerVersion
  Condition: DeployBoto3Layer
  Properties:
    LayerName: !Sub "${ResourcePrefix}Boto3-Layer"
    Description: "Boto3 and Botocore libraries for Python"
    Content:
      S3Bucket: !If [ProdCFNTemplateUsed, !FindInMap [RegionMap, !Ref "AWS::Region", CodeBucket], !Ref CFNSourceBucket]
      S3Key: "cfn/data-collection/v3.14.3/layers/boto3-layer.zip"
    CompatibleRuntimes:
      - python3.9
      - python3.10
      - python3.11
      - python3.12
      - python3.13
    CompatibleArchitectures:
      - x86_64
```

### Using the Layer in a Module

To use the Boto3 layer in your module, follow these steps:

#### 1. Add Parameter to Module Template

Add this parameter to your module's CloudFormation template:

```yaml
Parameters:
  Boto3LayerArn:
    Type: String
    Description: "ARN of the Boto3 Lambda Layer"
    Default: ""
```

#### 2. Add Condition

Add a condition to check if the layer ARN is provided:

```yaml
Conditions:
  UseBoto3Layer: !Not [ !Equals [ !Ref Boto3LayerArn, "" ] ]
```

#### 3. Reference Layer in Lambda Function

Add the `Layers` property to your Lambda function:

```yaml
LambdaFunction:
  Type: AWS::Lambda::Function
  Properties:
    FunctionName: !Sub '${ResourcePrefix}${CFDataName}-Lambda'
    Runtime: python3.13
    Architectures: [x86_64]
    Layers: !If
      - UseBoto3Layer
      - [!Ref Boto3LayerArn]
      - !Ref AWS::NoValue
    Code:
      # ... your code here
```

#### 4. Pass Layer ARN from Main Stack

In `deploy-data-collection.yaml`, pass the layer ARN to your module:

```yaml
YourModule:
  Type: AWS::CloudFormation::Stack
  Condition: DeployYourModule
  Properties:
    TemplateURL: !Sub "https://${CFNSourceBucket}.s3.${AWS::URLSuffix}/cfn/data-collection/v3.14.3/module-your-name.yaml"
    Parameters:
      # ... other parameters
      Boto3LayerArn: !Ref Boto3LayerVersion
```

#### 5. Update Deployment Condition (Optional)

If your module requires the Boto3 layer, update the `DeployBoto3Layer` condition in `deploy-data-collection.yaml`:

```yaml
Conditions:
  DeployBoto3Layer: !Or
    - !Condition DeployHealthEventsModule
    - !Condition DeployYourModule
```

## Example: Health Events Module

The Health Events module demonstrates the complete implementation:

**In module-health-events.yaml:**
```yaml
Parameters:
  Boto3LayerArn:
    Type: String
    Description: "ARN of the Boto3 Lambda Layer"
    Default: ""

Conditions:
  UseBoto3Layer: !Not [ !Equals [ !Ref Boto3LayerArn, "" ] ]

Resources:
  LambdaFunction:
    Type: AWS::Lambda::Function
    Properties:
      Runtime: python3.13
      Layers: !If
        - UseBoto3Layer
        - [!Ref Boto3LayerArn]
        - !Ref AWS::NoValue
```

**In deploy-data-collection.yaml:**
```yaml
HealthEventsModule:
  Type: AWS::CloudFormation::Stack
  Condition: DeployHealthEventsModule
  Properties:
    Parameters:
      Boto3LayerArn: !Ref Boto3LayerVersion
```

## Benefits

Using the Boto3 layer provides:

1. **Latest Features**: Access to the newest AWS service APIs and features
2. **Consistency**: All Lambdas use the same boto3 version
3. **Reduced Package Size**: Lambda deployment packages don't need to include boto3
4. **Easy Updates**: Update boto3 once in the layer, all Lambdas benefit
5. **Faster Deployments**: Smaller Lambda packages deploy faster
6. **Version Agnostic**: Single layer works across all Python 3.x runtimes

## Release Process Integration

The boto3 layer is built and published as part of the standard release process:

1. **Version Update**: Update version in `data-collection/utils/version.json`
2. **Build & Publish Layer**: Run `./data-collection/deploy/layers/publish-boto3-layer.sh`
3. **Sync Templates**: Run `./data-collection/utils/release.sh` to sync CloudFormation templates
4. **Deploy**: CloudFormation stacks reference the layer from regional buckets

## Development Workflow

### For Local Testing

1. Build the layer locally:
   ```bash
   cd data-collection/utils
   ./build-boto3-layer.sh
   ```

2. Upload to your test bucket:
   ```bash
   aws s3 cp boto3-layer.zip \
     s3://YOUR-TEST-BUCKET/cfn/data-collection/vX.Y.Z/layers/
   ```

3. Update your CloudFormation template to point to your test bucket

4. Deploy and test

### For Production Release

1. Ensure version is updated in `data-collection/utils/version.json`

2. Run the publish script:
   ```bash
   cd data-collection/deploy/layers
   ./publish-boto3-layer.sh
   ```

3. Run the main release script:
   ```bash
   cd data-collection/utils
   ./release.sh
   ```

## Troubleshooting

### Layer Not Found

If you get an error about the layer not being found:
- Ensure the layer has been published to the regional bucket
- Check the S3Key path matches your version in the CloudFormation template
- Verify the layer is being deployed (check the `DeployBoto3Layer` condition)

### Import Errors

If you get boto3 import errors:
- Verify the layer is attached to your Lambda function in the AWS Console
- Check the Lambda runtime is compatible (3.9-3.13)
- Ensure the layer was built with the correct directory structure (`python/` at root)

### Version Conflicts

If you need a specific boto3 version:
- Modify `build-boto3-layer.sh` to install a specific version: `pip3 install boto3==1.x.x`
- Rebuild and republish the layer
- Update all affected CloudFormation stacks

### Build Failures

If the build script fails:
- Ensure pip3 is installed and accessible
- Check network connectivity for package downloads
- Verify disk space is available for the build
- Check Python version compatibility

## Files

- `build-boto3-layer.sh` - Script to build the layer locally (this directory)
- `publish-boto3-layer.sh` - Script to build and publish to all regional buckets (this directory)
- `README.md` - This documentation file
- `boto3-layer.zip` - Generated layer file (not committed to git, created during build)

## References

- Build script: `data-collection/deploy/layers/build-boto3-layer.sh`
- Publish script: `data-collection/deploy/layers/publish-boto3-layer.sh`
- Main template: `data-collection/deploy/deploy-data-collection.yaml`
- Example module: `data-collection/deploy/module-health-events.yaml`
- Release script: `data-collection/utils/release.sh`
- AWS Lambda Layers: https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html

