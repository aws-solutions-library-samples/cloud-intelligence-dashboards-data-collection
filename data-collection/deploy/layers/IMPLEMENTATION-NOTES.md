# Boto3 Layer Implementation Notes

## Overview

This document describes the implementation of the boto3 Lambda layer for the Cloud Intelligence Dashboards Data Collection framework, following the same pattern as the case-summarization layer.

## Key Design Decisions

### 1. No Zip File in Repository

**Decision**: The `boto3-layer.zip` file is NOT committed to the repository.

**Rationale**:
- Follows the pattern established by case-summarization layer
- Reduces repository size
- Ensures fresh builds with latest boto3 for each release
- Avoids merge conflicts on binary files

**Implementation**: Added `data-collection/deploy/layers/boto3-layer.zip` to `.gitignore`

### 2. Version-Agnostic Layer Structure

**Decision**: Use simplified `python/` directory structure instead of `python/lib/python3.x/site-packages/`

**Rationale**:
- Single layer works across all Python 3.x runtimes (3.9-3.13)
- Simpler directory structure
- Easier maintenance - no need to update for new Python versions
- Fully supported by AWS Lambda

**Structure**:
```
boto3-layer.zip
└── python/
    ├── boto3/
    ├── botocore/
    └── [dependencies]
```

### 3. Build and Publish Separation

**Decision**: Separate build script (`build-boto3-layer.sh`) from publish script (`publish-boto3-layer.sh`)

**Rationale**:
- Build script can be used for local development/testing
- Publish script handles release process (build + upload to all regions)
- Follows case-summarization pattern
- Clear separation of concerns

## File Structure

```
data-collection/
├── utils/
│   └── release.sh                     # Main release script (unchanged)
└── deploy/
    └── layers/
        ├── build-boto3-layer.sh       # Builds the layer locally
        ├── publish-boto3-layer.sh     # Builds and publishes to all regions
        ├── README.md                  # Usage documentation
        ├── IMPLEMENTATION-NOTES.md    # This file
        └── boto3-layer.zip            # Generated (not in git)
```

## Scripts

### build-boto3-layer.sh

**Location**: `data-collection/deploy/layers/build-boto3-layer.sh`

**Purpose**: Build the boto3 layer locally

**Key Features**:
- Creates version-agnostic `python/` directory structure
- Installs latest boto3 and botocore
- Validates package structure
- Cleans up unnecessary files (.pyc, __pycache__, .dist-info)
- Outputs filename to stderr for scripting (like case-summarization)
- Creates zip in `data-collection/deploy/layers/boto3-layer.zip`

**Usage**:
```bash
cd data-collection/deploy/layers
./build-boto3-layer.sh
```

### publish-boto3-layer.sh

**Location**: `data-collection/deploy/layers/publish-boto3-layer.sh`

**Purpose**: Build and publish the layer to all regional S3 buckets

**Key Features**:
- Calls `build-boto3-layer.sh` to build the layer
- Reads version from `data-collection/utils/version.json`
- Uploads to central bucket: `aws-managed-cost-intelligence-dashboards`
- Uploads to all regional buckets via LayerBuckets StackSet
- Provides detailed progress and error reporting
- Cleans up local zip file after upload
- Follows case-summarization pattern exactly

**Usage**:
```bash
cd data-collection/deploy/layers
./publish-boto3-layer.sh
```

**Prerequisites**:
- AWS CLI configured
- LayerBuckets CloudFormation StackSet deployed
- Appropriate AWS credentials

## Integration with Release Process

The boto3 layer follows the same pattern as case-summarization:

1. **Version Update**: Update `data-collection/utils/version.json`
2. **Publish Layer**: Run `./data-collection/deploy/layers/publish-boto3-layer.sh`
3. **Sync Templates**: Run `./data-collection/utils/release.sh`

The layer is uploaded to:
- Central: `s3://aws-managed-cost-intelligence-dashboards/cfn/data-collection/vX.Y.Z/layers/boto3-layer.zip`
- Regional: `s3://REGIONAL-BUCKET/cfn/data-collection/vX.Y.Z/layers/boto3-layer.zip`

## CloudFormation Integration

### Main Stack (deploy-data-collection.yaml)

```yaml
Conditions:
  DeployBoto3Layer: !Condition DeployHealthEventsModule

Resources:
  Boto3LayerVersion:
    Type: AWS::Lambda::LayerVersion
    Condition: DeployBoto3Layer
    Properties:
      LayerName: !Sub "${ResourcePrefix}Boto3-Layer"
      Content:
        S3Bucket: !If [ProdCFNTemplateUsed, !FindInMap [RegionMap, !Ref "AWS::Region", CodeBucket], !Ref CFNSourceBucket]
        S3Key: "cfn/data-collection/v3.14.3/layers/boto3-layer.zip"
      CompatibleRuntimes:
        - python3.9
        - python3.10
        - python3.11
        - python3.12
        - python3.13

  HealthEventsModule:
    Properties:
      Parameters:
        Boto3LayerArn: !Ref Boto3LayerVersion
```

### Module Stack (module-health-events.yaml)

```yaml
Parameters:
  Boto3LayerArn:
    Type: String
    Default: ""

Conditions:
  UseBoto3Layer: !Not [ !Equals [ !Ref Boto3LayerArn, "" ] ]

Resources:
  LambdaFunction:
    Properties:
      Layers: !If
        - UseBoto3Layer
        - [!Ref Boto3LayerArn]
        - !Ref AWS::NoValue
```

## Comparison with Case-Summarization

| Aspect | Case-Summarization | Boto3 Layer |
|--------|-------------------|-------------|
| Build Script | `case-summarization/layer/build-layer.sh` | `data-collection/deploy/layers/build-boto3-layer.sh` |
| Publish Script | `case-summarization/layer/publish-lambda-layer.sh` | `data-collection/deploy/layers/publish-boto3-layer.sh` |
| Output Location | `case-summarization/layer/` | `data-collection/deploy/layers/` |
| Zip Filename | `llm-VERSION.zip` | `boto3-layer.zip` |
| S3 Path | `cid-llm-lambda-layer/llm-VERSION.zip` | `cfn/data-collection/vVERSION/layers/boto3-layer.zip` |
| Version Source | `case-summarization/utils/version.json` | `data-collection/utils/version.json` |
| Dependencies | requirements.txt | Latest boto3 (no requirements file) |
| Structure | `python/` | `python/` (version-agnostic) |

## Benefits

1. **Consistency**: Follows established patterns in the codebase
2. **Maintainability**: Clear separation of build and publish logic
3. **Flexibility**: Can build locally for testing without publishing
4. **Automation**: Easy to integrate into CI/CD pipelines
5. **Version Control**: No binary files in git
6. **Cross-Runtime**: Single layer works with all Python 3.x versions

## Future Enhancements

Potential improvements for future consideration:

1. **CI/CD Integration**: Automate layer publishing in GitHub Actions
2. **Version Pinning**: Option to pin specific boto3 version if needed
3. **Layer Versioning**: Track layer versions separately from stack version
4. **Automated Testing**: Test layer compatibility across Python runtimes
5. **Size Optimization**: Further reduce layer size if needed

## Testing

### Local Testing

1. Build the layer:
   ```bash
   cd data-collection/deploy/layers
   ./build-boto3-layer.sh
   ```

2. Verify structure:
   ```bash
   unzip -l data-collection/deploy/layers/boto3-layer.zip | head -20
   ```

3. Upload to test bucket:
   ```bash
   aws s3 cp data-collection/deploy/layers/boto3-layer.zip \
     s3://YOUR-TEST-BUCKET/cfn/data-collection/vX.Y.Z/layers/
   ```

### Release Testing

1. Update version in `data-collection/utils/version.json`
2. Run publish script:
   ```bash
   ./data-collection/deploy/layers/publish-boto3-layer.sh
   ```
3. Verify uploads to all regions
4. Deploy test stack with new layer
5. Verify Lambda functions can import boto3

## Troubleshooting

### Build Issues

**Problem**: pip install fails
**Solution**: Check network connectivity, verify pip3 is installed

**Problem**: Validation errors
**Solution**: Check that boto3 and botocore directories exist in `python/`

### Publish Issues

**Problem**: S3 upload fails
**Solution**: Verify AWS credentials, check bucket permissions

**Problem**: Can't find regional buckets
**Solution**: Ensure LayerBuckets StackSet is deployed

### Runtime Issues

**Problem**: Lambda can't import boto3
**Solution**: Verify layer is attached, check runtime compatibility

**Problem**: Wrong boto3 version
**Solution**: Rebuild and republish layer with latest boto3

## References

- Case-summarization layer: `case-summarization/layer/`
- Main release script: `data-collection/utils/release.sh`
- AWS Lambda Layers: https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html
- Boto3 Documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/index.html
