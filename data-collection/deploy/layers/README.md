# Lambda Layer for Boto3

This directory contains the Lambda layer package for boto3 and botocore libraries used by the Cloud Intelligence Dashboards data collection modules.

## Overview

The Lambda layer provides a centralized, up-to-date version of boto3 and botocore that can be shared across all Lambda functions in the data collection modules. This approach:

- Reduces individual Lambda deployment package sizes
- Ensures consistent AWS SDK versions across all functions
- Simplifies updates to the AWS SDK
- Improves deployment speed

## Layer Package Location

The layer package is stored in this directory:

```
data-collection/deploy/layers/boto3-layer.zip
```

This zip file contains boto3, botocore, and their dependencies in the correct directory structure required by AWS Lambda.

## Building the Layer

### Prerequisites

- Python 3.13 or compatible version
- pip3 (Python package installer)
- zip utility
- Internet connection (to download packages)

### Build Script

Use the utility script to build the Lambda layer package:

```bash
# From the project root directory
./data-collection/utils/build-boto3-layer.sh
```

The script will:

1. Create a temporary directory structure at `.tmp/python/lib/python3.13/site-packages/`
2. Install the latest boto3 and botocore packages using pip
3. Remove unnecessary files (*.pyc, __pycache__, *.dist-info)
4. Validate the package structure
5. Create a zip file with the correct directory layout
6. Output the zip to `data-collection/deploy/layers/boto3-layer.zip`
7. Display installed versions and package size
8. Clean up temporary files

### Build Output

The script provides detailed output including:

```
Lambda Layer Build Summary
==========================================
Output file:      data-collection/deploy/layers/boto3-layer.zip
File size:        15M
boto3 version:    1.35.0
botocore version: 1.35.0
Python version:   3.13
==========================================
```

## Deploying the Layer

### Step 1: Upload to S3

After building the layer package, upload it to your S3 bucket:

```bash
aws s3 cp data-collection/deploy/layers/boto3-layer.zip \
  s3://YOUR-BUCKET/cfn/data-collection/VERSION/layers/
```

Replace:
- `YOUR-BUCKET` with your CloudFormation source bucket name
- `VERSION` with your deployment version (e.g., v3.14.3)

### Step 2: Deploy CloudFormation Stack

The Lambda layer is automatically deployed when you deploy the main CloudFormation stack with the Health Events module enabled:

```bash
aws cloudformation deploy \
  --template-file data-collection/deploy/deploy-data-collection.yaml \
  --stack-name cid-data-collection \
  --parameter-overrides \
    DeployHealthEventsModule=yes \
    # ... other parameters
```

The layer deploys automatically when `DeployHealthEventsModule=yes` - no additional configuration needed.

### Step 3: Verify Deployment

Check that the layer was created:

```bash
aws lambda list-layer-versions \
  --layer-name CID-DC-Boto3-Layer \
  --region us-east-1
```

## Module Integration

### How It Works

The Lambda layer is defined in the main CloudFormation template (`deploy-data-collection.yaml`) and automatically passed to modules that need it.

**Main Template:**
```yaml
Boto3LayerVersion:
  Type: AWS::Lambda::LayerVersion
  Condition: DeployHealthEventsModule
  Properties:
    LayerName: !Sub "${ResourcePrefix}Boto3-Layer"
    Content:
      S3Bucket: !Ref CFNSourceBucket
      S3Key: !Sub "cfn/data-collection/${StackVersion}/layers/boto3-layer.zip"
    CompatibleRuntimes:
      - python3.13

Outputs:
  Boto3LayerArn:
    Condition: DeployHealthEventsModule
    Value: !Ref Boto3LayerVersion
```

### Integrating into New Modules

To use the Lambda layer in a new module:

#### 1. Add Parameter to Module Template

```yaml
Parameters:
  Boto3LayerArn:
    Type: String
    Description: "ARN of the Boto3 Lambda Layer (optional)"
    Default: ""
```

#### 2. Add Condition for Layer Usage

```yaml
Conditions:
  UseBoto3Layer: !Not [!Equals [!Ref Boto3LayerArn, ""]]
```

#### 3. Update Lambda Function Resource

```yaml
LambdaFunction:
  Type: AWS::Lambda::Function
  Properties:
    FunctionName: !Sub '${ResourcePrefix}${CFDataName}-Lambda'
    Runtime: python3.13
    Layers: !If
      - UseBoto3Layer
      - [!Ref Boto3LayerArn]
      - !Ref AWS::NoValue
    # ... other properties
```

#### 4. Pass Layer ARN from Main Template

In `deploy-data-collection.yaml`, add the parameter when invoking your module:

```yaml
YourModule:
  Type: AWS::CloudFormation::Stack
  Condition: DeployYourModule
  Properties:
    TemplateURL: !Sub "https://${CFNSourceBucket}.s3.${AWS::URLSuffix}/cfn/data-collection/${StackVersion}/module-your-module.yaml"
    Parameters:
      # ... existing parameters
      Boto3LayerArn: !If
        - DeployHealthEventsModule
        - !Ref Boto3LayerVersion
        - ""
```

### Example: Health Events Module

The health-events module serves as a reference implementation. See `module-health-events.yaml` for a complete example of layer integration.

## Layer Package Structure

The layer zip file has the following structure required by AWS Lambda:

```
boto3-layer.zip
└── python/
    └── lib/
        └── python3.13/
            └── site-packages/
                ├── boto3/
                │   ├── __init__.py
                │   ├── session.py
                │   └── ...
                ├── botocore/
                │   ├── __init__.py
                │   ├── client.py
                │   └── ...
                ├── s3transfer/
                ├── jmespath/
                ├── dateutil/
                └── urllib3/
```

Key requirements:
- The `python/` directory must be at the root of the zip file
- The path must match the Python version: `python3.13`
- All dependencies of boto3 are included automatically
- No compiled files (*.pyc) or cache directories

## Troubleshooting

### Build Script Issues

#### Error: "pip3 not found"

**Cause:** Python 3 or pip3 is not installed.

**Solution:**
```bash
# macOS
brew install python3

# Ubuntu/Debian
sudo apt-get install python3-pip

# Amazon Linux 2
sudo yum install python3-pip
```

#### Error: "zip command not found"

**Cause:** The zip utility is not installed.

**Solution:**
```bash
# macOS (usually pre-installed)
brew install zip

# Ubuntu/Debian
sudo apt-get install zip

# Amazon Linux 2
sudo yum install zip
```

#### Error: "Failed to install boto3"

**Cause:** Network connectivity issues or pip configuration problems.

**Solution:**
- Check internet connectivity
- Verify pip is up to date: `pip3 install --upgrade pip`
- Try with verbose output: `pip3 install boto3 --verbose`
- Check for proxy settings if behind a corporate firewall

#### Error: "Package validation failed"

**Cause:** The build process didn't create the expected directory structure or packages.

**Solution:**
- Delete the `.tmp/` directory and try again
- Verify pip installation succeeded without errors
- Check disk space: `df -h`
- Review the build script output for specific validation errors

#### Warning: "Zip file exceeds recommended size"

**Cause:** The layer package is larger than 50 MB (compressed).

**Solution:**
- This is usually not an issue for boto3 layers (typically 15-20 MB)
- If size is a concern, consider removing unnecessary dependencies
- Lambda layers have a 50 MB compressed / 250 MB uncompressed limit

### Deployment Issues

#### Error: "Layer package not found in S3"

**Cause:** The layer zip file wasn't uploaded to S3 or the S3 key is incorrect.

**Solution:**
- Verify the file was uploaded: `aws s3 ls s3://YOUR-BUCKET/cfn/data-collection/VERSION/layers/`
- Check the S3Key in the CloudFormation template matches the uploaded file path
- Ensure the S3 bucket name and region are correct

#### Error: "Invalid layer content"

**Cause:** The zip file doesn't meet Lambda layer requirements.

**Solution:**
- Rebuild the layer using the build script
- Verify the zip structure: `unzip -l boto3-layer.zip | head -20`
- Ensure the `python/` directory is at the root of the zip
- Check that the Python version path matches: `python3.13`

#### Error: "Runtime incompatibility"

**Cause:** Lambda function runtime doesn't match the layer's compatible runtimes.

**Solution:**
- Ensure Lambda function uses `Runtime: python3.13`
- Verify the layer's CompatibleRuntimes includes python3.13
- Check CloudFormation template for runtime mismatches

### Runtime Issues

#### Error: "ModuleNotFoundError: No module named 'boto3'"

**Cause:** The layer isn't attached to the Lambda function or the layer package is invalid.

**Solution:**
- Verify the layer ARN is passed to the module template
- Check the Lambda function's Layers property in CloudFormation
- Confirm the layer was deployed successfully
- Test the layer package locally by extracting and importing boto3

#### Error: "AttributeError" or API incompatibility

**Cause:** The Lambda function code requires a specific boto3 version not in the layer.

**Solution:**
- Check the required boto3 version in your code
- Rebuild the layer with a specific boto3 version if needed
- Update the build script to install a specific version: `pip3 install boto3==1.35.0`
- Consider pinning boto3 version in requirements if compatibility is critical

#### Lambda function not using layer boto3

**Cause:** Lambda includes a built-in boto3 version that may take precedence.

**Solution:**
- The layer boto3 should automatically override the built-in version
- Verify the layer is attached: Check Lambda console or describe-function CLI
- Test by printing boto3 version in Lambda: `print(boto3.__version__)`
- Ensure the layer path is correct in the zip file

### Version Management

#### How to update boto3 version

To update to the latest boto3 version:

1. Run the build script (it always installs the latest version):
   ```bash
   ./data-collection/utils/build-boto3-layer.sh
   ```

2. Upload the new layer package to S3

3. Redeploy the CloudFormation stack (this creates a new layer version)

4. Lambda functions will automatically use the new layer version

#### How to use a specific boto3 version

Modify the build script to install a specific version:

```bash
# In build-boto3-layer.sh, change this line:
pip3 install boto3 --target "$LAYER_DIR" --upgrade --quiet

# To this (replace 1.35.0 with your desired version):
pip3 install boto3==1.35.0 --target "$LAYER_DIR" --quiet
```

Then rebuild and redeploy.

## Best Practices

### When to Use the Layer

Use the Lambda layer when:
- Your Lambda function needs the latest boto3 features
- You want to reduce deployment package size
- You want consistent boto3 versions across multiple functions
- You're deploying modules that benefit from shared dependencies

### When Not to Use the Layer

Don't use the layer when:
- Your Lambda function requires a specific, pinned boto3 version
- The built-in boto3 version is sufficient for your needs
- You need to minimize cold start time (layers add minimal overhead)

### Layer Size Optimization

To keep the layer size small:
- The build script automatically removes *.pyc files and __pycache__ directories
- The build script removes *.dist-info directories
- Only boto3 and its required dependencies are included
- No test files or documentation are included

### Testing the Layer

Before deploying to production:

1. **Test locally:**
   ```bash
   # Extract the layer
   unzip -q boto3-layer.zip -d test-layer
   
   # Test import
   python3 -c "import sys; sys.path.insert(0, 'test-layer/python/lib/python3.13/site-packages'); import boto3; print(boto3.__version__)"
   ```

2. **Test in Lambda:**
   - Deploy to a test environment first
   - Verify Lambda functions can import boto3
   - Check CloudWatch logs for any import errors
   - Test actual AWS API calls

3. **Verify version:**
   ```python
   import boto3
   print(f"boto3 version: {boto3.__version__}")
   ```

## Additional Resources

- [AWS Lambda Layers Documentation](https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html)
- [Boto3 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- [Python Lambda Deployment Packages](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the build script output for specific error messages
3. Verify all prerequisites are installed
4. Check CloudFormation stack events for deployment errors
5. Review Lambda function logs in CloudWatch

## Version History

The layer package version is tracked through:
- CloudFormation stack version (StackVersion parameter)
- Lambda layer version number (auto-incremented by AWS)
- boto3 version in the package (displayed by build script)

To check the current layer version:
```bash
aws lambda list-layer-versions \
  --layer-name CID-DC-Boto3-Layer \
  --region us-east-1 \
  --max-items 1
```
