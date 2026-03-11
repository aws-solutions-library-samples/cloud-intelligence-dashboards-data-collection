# Design Document: Lambda Layer for Boto3

## Overview

This design implements a centralized Lambda layer containing the latest boto3 and botocore libraries for the Cloud Intelligence Dashboards data collection project. The layer will be defined in the main CloudFormation template and made available to all module templates through parameter passing and cross-stack references.

The solution consists of three main components:
1. A build script that creates the Lambda layer package with the correct directory structure
2. CloudFormation resources in the main template to define and deploy the layer
3. Integration points in module templates to reference and use the layer

This approach reduces Lambda deployment package sizes, ensures consistent boto3 versions across all functions, and simplifies updates to the AWS SDK.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Main CloudFormation Stack                 │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │         Lambda Layer (Boto3LayerVersion)           │    │
│  │  - Contains: boto3 + botocore                      │    │
│  │  - Runtime: Python 3.13                            │    │
│  │  - Source: S3 (CodeBucket)                         │    │
│  └────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          │ (Export ARN)                      │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────┐    │
│  │              Stack Outputs                         │    │
│  │  - Boto3LayerArn: !Ref Boto3LayerVersion          │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (Pass as Parameter)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Module CloudFormation Stacks                │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Parameters:                                       │    │
│  │    Boto3LayerArn: (from main stack)               │    │
│  └────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────┐    │
│  │         Lambda Function                            │    │
│  │  Properties:                                       │    │
│  │    Runtime: python3.13                             │    │
│  │    Layers:                                         │    │
│  │      - !Ref Boto3LayerArn                          │    │
│  │    Code: (module-specific logic)                   │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Build and Deployment Flow

```
┌──────────────┐
│  Developer   │
└──────┬───────┘
       │
       │ 1. Run build script
       ▼
┌──────────────────────────────┐
│  build-boto3-layer.sh        │
│  - pip install boto3         │
│  - Create directory structure│
│  - Zip package               │
└──────┬───────────────────────┘
       │
       │ 2. Upload to S3
       ▼
┌──────────────────────────────┐
│  S3 CodeBucket               │
│  /layers/boto3-layer.zip     │
└──────┬───────────────────────┘
       │
       │ 3. Deploy CloudFormation
       ▼
┌──────────────────────────────┐
│  Main Stack                  │
│  - Creates LayerVersion      │
│  - Exports ARN               │
└──────┬───────────────────────┘
       │
       │ 4. Pass ARN to modules
       ▼
┌──────────────────────────────┐
│  Module Stacks               │
│  - Reference layer in Lambda │
└──────────────────────────────┘
```

## Components and Interfaces

### 1. Build Utility Script (build-boto3-layer.sh)

**Purpose:** Creates a Lambda layer package with boto3 and botocore libraries in the correct directory structure.

**Location:** `data-collection/utils/build-boto3-layer.sh`

**Interface:**
```bash
./build-boto3-layer.sh
```

**Behavior:**
1. Creates temporary directory in `.tmp/` relative to project root
2. Creates directory structure: `.tmp/python/lib/python3.13/site-packages/`
3. Installs latest boto3 (and botocore as dependency) using pip with `--target` option
4. Removes unnecessary files (*.pyc, __pycache__, *.dist-info)
5. Creates zip file with the python/ directory at the root
6. Outputs the installed versions and package size
7. Validates the package structure
8. Moves zip file to `data-collection/deploy/layers/boto3-layer.zip`
9. Cleans up `.tmp/` directory

**Output:**
- `data-collection/deploy/layers/boto3-layer.zip`: Lambda layer package ready for deployment
- Console output showing installed versions and package details

### 2. Lambda Layer Resource (Main Template)

**CloudFormation Resource:**
```yaml
Boto3LayerVersion:
  Type: AWS::Lambda::LayerVersion
  Properties:
    LayerName: !Sub "${ResourcePrefix}Boto3-Layer"
    Description: !Sub "Boto3 and Botocore libraries for Python 3.13 (boto3 ${Boto3Version})"
    Content:
      S3Bucket: !If [ProdCFNTemplateUsed, !FindInMap [RegionMap, !Ref "AWS::Region", CodeBucket], !Ref CFNSourceBucket]
      S3Key: !Sub "cfn/data-collection/${StackVersion}/layers/boto3-layer.zip"
    CompatibleRuntimes:
      - python3.13
    CompatibleArchitectures:
      - x86_64
```

**Condition (reuses existing Health Events condition):**
```yaml
# Layer deploys when Health Events module is enabled
# Uses existing DeployHealthEventsModule condition
```

**Output:**
```yaml
Boto3LayerArn:
  Condition: DeployHealthEventsModule
  Description: "ARN of the Boto3 Lambda Layer"
  Value: !Ref Boto3LayerVersion
  Export:
    Name: !Sub "${AWS::StackName}-Boto3LayerArn"
```

### 3. Module Template Integration

**Parameter Addition:**
```yaml
Boto3LayerArn:
  Type: String
  Description: "ARN of the Boto3 Lambda Layer (optional)"
  Default: ""
```

**Condition:**
```yaml
UseBoto3Layer: !Not [!Equals [!Ref Boto3LayerArn, ""]]
```

**Lambda Function Modification:**
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

**Main Stack Module Invocation:**
```yaml
HealthEventsModule:
  Type: AWS::CloudFormation::Stack
  Condition: DeployHealthEventsModule
  Properties:
    TemplateURL: !Sub "https://${CFNSourceBucket}.s3.${AWS::URLSuffix}/cfn/data-collection/v3.14.3/module-health-events.yaml"
    Parameters:
      # ... existing parameters
      Boto3LayerArn: !Ref Boto3LayerVersion
```

### 4. Layer Package Structure

**Directory Layout:**
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

**Key Requirements:**
- The `python/` directory must be at the root of the zip file
- The path must match the Python version: `python3.13`
- All dependencies of boto3 must be included (botocore, s3transfer, jmespath, etc.)
- No compiled files or cache directories

## Data Models

### Build Script Configuration

```python
class LayerBuildConfig:
    """Configuration for building the Lambda layer"""
    boto3_version: str = "latest"  # or specific version like "1.35.0"
    python_version: str = "3.13"
    output_dir: str = "./layer-build"
    output_file: str = "boto3-layer.zip"
    include_packages: list[str] = ["boto3"]  # botocore installed as dependency
    exclude_patterns: list[str] = [
        "*.pyc",
        "__pycache__",
        "*.dist-info",
        "tests/",
        "*.egg-info"
    ]
```

### CloudFormation Parameter Schema

```yaml
# Module Template Parameters  
ModuleTemplateParams:
  Boto3LayerArn: string  # ARN or empty string (empty when module not deployed)
```

### Layer Metadata

```python
class LayerMetadata:
    """Metadata about the deployed layer"""
    layer_name: str  # e.g., "CID-DC-Boto3-Layer"
    layer_arn: str   # e.g., "arn:aws:lambda:us-east-1:123456789012:layer:CID-DC-Boto3-Layer:1"
    version: int     # Layer version number
    boto3_version: str  # e.g., "1.35.0"
    botocore_version: str  # e.g., "1.35.0"
    compatible_runtimes: list[str] = ["python3.13"]
    size_bytes: int  # Package size
    created_date: str  # ISO 8601 timestamp
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Property Reflection

After analyzing the acceptance criteria, I identified the following testable properties:

**Properties identified:**
1. Package structure validation (1.4) - zip contains correct directory structure and packages
2. Build reproducibility (1.5) - same inputs produce equivalent outputs
3. Directory structure in zip (2.3) - all zips have python/lib/python3.13/site-packages/
4. Invalid structure detection (2.5) - script fails on invalid structure

**Redundancy analysis:**
- Property 1 (package structure) and Property 3 (directory structure) are related but distinct:
  - Property 1 checks for presence of boto3/botocore packages AND correct structure
  - Property 3 checks only for directory structure
  - Property 1 subsumes Property 3, so Property 3 can be removed
- Property 2 (reproducibility) and Property 4 (validation) are independent
- Property 4 is an error condition test, which is valuable for robustness

**Final properties after reflection:**
1. Package structure and content validation (combines 1.4 and 2.3)
2. Build reproducibility (1.5)
3. Invalid structure detection (2.5)

### Correctness Properties

Property 1: Layer package structure and content
*For any* Lambda layer zip file created by the build script, the zip file should contain a `python/lib/python3.13/site-packages/` directory structure, and that directory should contain both `boto3` and `botocore` package directories with their respective `__init__.py` files.
**Validates: Requirements 1.4, 2.3**

Property 2: Build reproducibility
*For any* set of build parameters (boto3 version, python version), running the build script multiple times with the same parameters should produce zip files with equivalent content (same files, same sizes, same package versions).
**Validates: Requirements 1.5**

Property 3: Invalid structure rejection
*For any* invalid package structure (missing python/ directory, wrong Python version path, missing required packages), the build script validation should fail and prevent zip file creation.
**Validates: Requirements 2.5**

## Error Handling

### Build Script Errors

**Error Scenarios:**
1. **Pip installation failure**: If boto3 or dependencies fail to install
   - Action: Exit with error code 1, display pip error message
   - Recovery: Check network connectivity, verify Python version compatibility

2. **Insufficient disk space**: If not enough space for package installation
   - Action: Exit with error code 2, display disk space error
   - Recovery: Free up disk space or specify different output directory

3. **Invalid directory structure**: If required directories cannot be created
   - Action: Exit with error code 3, display permission error
   - Recovery: Check directory permissions, run with appropriate privileges

4. **Zip creation failure**: If zip command fails or zip file is corrupted
   - Action: Exit with error code 4, display zip error
   - Recovery: Verify zip utility is installed, check output directory permissions

5. **Validation failure**: If created package doesn't meet requirements
   - Action: Exit with error code 5, display validation errors
   - Recovery: Review build logs, verify pip installation succeeded

**Error Output Format:**
```
ERROR: [Error Type]
Details: [Specific error message]
Suggestion: [Recovery action]
Exit Code: [1-5]
```

### CloudFormation Deployment Errors

**Error Scenarios:**
1. **Layer package not found in S3**: If S3Key doesn't exist
   - CloudFormation Error: Resource creation failed
   - Resolution: Upload layer package to S3 before deploying stack

2. **Invalid layer package**: If zip file doesn't meet Lambda requirements
   - CloudFormation Error: Invalid layer content
   - Resolution: Rebuild layer package with correct structure

3. **Layer size exceeds limit**: If unzipped package > 250 MB
   - CloudFormation Error: Layer size limit exceeded
   - Resolution: Remove unnecessary files, optimize package size

4. **Missing layer ARN parameter**: If module deployed without layer ARN when expected
   - CloudFormation Error: Parameter validation failed
   - Resolution: Provide layer ARN or set to empty string for optional use

5. **Incompatible runtime**: If Lambda function runtime doesn't match layer
   - CloudFormation Error: Runtime incompatibility
   - Resolution: Ensure Lambda function uses python3.13 runtime

### Runtime Errors

**Error Scenarios:**
1. **Import errors**: If boto3 import fails in Lambda function
   - Lambda Error: ModuleNotFoundError
   - Resolution: Verify layer is attached, check layer package contents

2. **Version conflicts**: If code requires specific boto3 version not in layer
   - Lambda Error: AttributeError or API incompatibility
   - Resolution: Update layer with required boto3 version

3. **Permission errors**: If Lambda can't access layer
   - Lambda Error: AccessDeniedException
   - Resolution: Verify Lambda execution role has layer access permissions

## Testing Strategy

### Unit Tests

Unit tests will focus on specific components and edge cases:

1. **Build Script Tests**
   - Test script with valid parameters produces expected output
   - Test script with invalid parameters fails appropriately
   - Test script with missing dependencies reports clear errors
   - Test version specification works correctly
   - Test output directory creation and cleanup

2. **CloudFormation Template Tests**
   - Test template syntax is valid (cfn-lint)
   - Test parameter validation works correctly
   - Test conditional logic for layer deployment
   - Test output exports are correctly defined
   - Test module template parameter handling

3. **Integration Tests**
   - Test layer package can be uploaded to S3
   - Test CloudFormation stack deploys successfully
   - Test Lambda function with layer can import boto3
   - Test Lambda function without layer still works
   - Test health events module with layer maintains functionality

### Property-Based Tests

Property-based tests will verify universal properties across all inputs. Each test will run a minimum of 100 iterations with randomized inputs.

**Test Configuration:**
- Framework: pytest with hypothesis (Python)
- Iterations per test: 100 minimum
- Test tagging: Each test references its design property

**Property Test 1: Layer package structure validation**
```python
@given(
    boto3_version=st.sampled_from(["1.34.0", "1.35.0", "latest"]),
    python_version=st.just("3.13"),
    output_dir=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N')))
)
@settings(max_examples=100)
def test_layer_package_structure(boto3_version, python_version, output_dir):
    """
    Feature: lambda-layer-boto3, Property 1: Layer package structure and content
    
    For any Lambda layer zip file created by the build script, the zip file should 
    contain a python/lib/python3.13/site-packages/ directory structure, and that 
    directory should contain both boto3 and botocore package directories with their 
    respective __init__.py files.
    """
    # Run build script with parameters
    result = run_build_script(boto3_version, python_version, output_dir)
    
    # Verify zip file was created
    assert result.zip_file_exists
    
    # Extract and verify structure
    with zipfile.ZipFile(result.zip_path) as zf:
        files = zf.namelist()
        
        # Check directory structure
        assert any(f.startswith("python/lib/python3.13/site-packages/") for f in files)
        
        # Check boto3 package
        assert "python/lib/python3.13/site-packages/boto3/__init__.py" in files
        
        # Check botocore package
        assert "python/lib/python3.13/site-packages/botocore/__init__.py" in files
```

**Property Test 2: Build reproducibility**
```python
@given(
    boto3_version=st.sampled_from(["1.34.0", "1.35.0"]),
    python_version=st.just("3.13")
)
@settings(max_examples=100)
def test_build_reproducibility(boto3_version, python_version):
    """
    Feature: lambda-layer-boto3, Property 2: Build reproducibility
    
    For any set of build parameters (boto3 version, python version), running the 
    build script multiple times with the same parameters should produce zip files 
    with equivalent content (same files, same sizes, same package versions).
    """
    # Run build script twice with same parameters
    result1 = run_build_script(boto3_version, python_version, "build1")
    result2 = run_build_script(boto3_version, python_version, "build2")
    
    # Compare zip file contents
    with zipfile.ZipFile(result1.zip_path) as zf1, \
         zipfile.ZipFile(result2.zip_path) as zf2:
        
        files1 = sorted(zf1.namelist())
        files2 = sorted(zf2.namelist())
        
        # Same files
        assert files1 == files2
        
        # Same file sizes (excluding timestamps)
        for file in files1:
            if not file.endswith('.pyc'):  # Exclude compiled files
                info1 = zf1.getinfo(file)
                info2 = zf2.getinfo(file)
                assert info1.file_size == info2.file_size
    
    # Verify same package versions
    assert result1.boto3_version == result2.boto3_version
    assert result1.botocore_version == result2.botocore_version
```

**Property Test 3: Invalid structure rejection**
```python
@given(
    invalid_structure=st.sampled_from([
        "missing_python_dir",
        "wrong_python_version",
        "missing_boto3",
        "missing_botocore",
        "empty_packages"
    ])
)
@settings(max_examples=100)
def test_invalid_structure_rejection(invalid_structure):
    """
    Feature: lambda-layer-boto3, Property 3: Invalid structure rejection
    
    For any invalid package structure (missing python/ directory, wrong Python 
    version path, missing required packages), the build script validation should 
    fail and prevent zip file creation.
    """
    # Create invalid structure based on test case
    temp_dir = create_invalid_structure(invalid_structure)
    
    # Run validation
    result = run_validation(temp_dir)
    
    # Verify validation failed
    assert result.failed
    assert result.exit_code == 5
    assert "validation" in result.error_message.lower()
    
    # Verify no zip file was created
    assert not result.zip_file_exists
```

### Test Execution

**Unit Tests:**
```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_build_script.py -v

# Run with coverage
pytest tests/unit/ --cov=src --cov-report=html
```

**Property-Based Tests:**
```bash
# Run all property tests
pytest tests/properties/ -v

# Run with more examples for thorough testing
pytest tests/properties/ --hypothesis-show-statistics

# Run specific property test
pytest tests/properties/test_layer_structure.py::test_layer_package_structure -v
```

**Integration Tests:**
```bash
# Run integration tests (requires AWS credentials)
pytest tests/integration/ -v --aws-profile=test

# Run specific integration test
pytest tests/integration/test_cloudformation_deployment.py -v
```

### Test Coverage Goals

- Unit test coverage: > 80% of build script code
- Property test coverage: All correctness properties from design
- Integration test coverage: All major deployment scenarios
- Edge case coverage: All error conditions documented

### Continuous Integration

Tests should be run automatically on:
- Every pull request
- Every commit to main branch
- Nightly builds for extended property testing (1000+ iterations)
- Before each release

**CI Pipeline:**
```yaml
stages:
  - lint
  - unit-test
  - property-test
  - integration-test
  - deploy

lint:
  script:
    - cfn-lint templates/*.yaml
    - shellcheck scripts/*.sh
    
unit-test:
  script:
    - pytest tests/unit/ --cov=src --cov-report=xml
    
property-test:
  script:
    - pytest tests/properties/ --hypothesis-show-statistics
    
integration-test:
  script:
    - pytest tests/integration/ --aws-profile=ci
  only:
    - main
    - tags
```
