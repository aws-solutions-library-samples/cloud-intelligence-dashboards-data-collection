# Implementation Plan: Lambda Layer for Boto3

## Overview

This implementation plan breaks down the Lambda layer feature into discrete coding tasks. The approach follows an incremental pattern: build the utility script first, then add CloudFormation resources to the main template, and finally integrate with the health-events module template.

The layer deploys automatically when the Health Events module is enabled - no user configuration required.

## Tasks

- [x] 1. Create utility script for Lambda layer package
  - Create `data-collection/utils/build-boto3-layer.sh`
  - Implement directory structure creation in `.tmp/python/lib/python3.13/site-packages/`
  - Implement pip installation with --target option for latest boto3
  - Implement cleanup of unnecessary files (*.pyc, __pycache__, *.dist-info)
  - Implement zip file creation with correct structure
  - Implement version detection and output display
  - Add validation logic to verify package structure
  - Output zip to `data-collection/deploy/layers/boto3-layer.zip`
  - Clean up `.tmp/` directory after build
  - Make script executable (chmod +x)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ]* 1.1 Write property test for layer package structure
  - **Property 1: Layer package structure and content**
  - **Validates: Requirements 1.4, 2.3**

- [ ]* 1.2 Write property test for invalid structure rejection
  - **Property 2: Invalid structure rejection**
  - **Validates: Requirements 2.5**

- [x] 2. Add Lambda layer resource to main CloudFormation template
  - [x] 2.1 Add Lambda layer resource
    - Add `Boto3LayerVersion` resource of type AWS::Lambda::LayerVersion
    - Reference layer file from data-collection/deploy/layers/boto3-layer.zip
    - Set CompatibleRuntimes to python3.13
    - Set CompatibleArchitectures to x86_64
    - Add description indicating boto3 layer
    - Apply DeployHealthEventsModule condition (reuse existing condition)
    - _Requirements: 1.1, 3.1, 3.2, 3.3, 3.5, 6.1, 6.2, 6.3_
  
  - [x] 2.2 Add output for layer ARN
    - Add `Boto3LayerArn` output with DeployHealthEventsModule condition
    - Export layer ARN for cross-stack references
    - _Requirements: 3.4_

- [ ]* 2.3 Write unit tests for CloudFormation template
  - Test conditional logic
  - Test output exports
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Checkpoint - Verify main template changes
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Integrate layer into health-events module template
  - [x] 4.1 Add parameter to module-health-events.yaml
    - Add `Boto3LayerArn` parameter (string, default: "")
    - _Requirements: 4.2, 5.1_
  
  - [x] 4.2 Add condition for layer usage
    - Add `UseBoto3Layer` condition checking if Boto3LayerArn is not empty
    - _Requirements: 4.1, 6.4_
  
  - [x] 4.3 Update Lambda function resource
    - Add Layers property to LambdaFunction resource
    - Use conditional reference to Boto3LayerArn
    - Use !Ref AWS::NoValue when layer not provided
    - _Requirements: 4.3, 5.2_
  
  - [x] 4.4 Update main template to pass layer ARN to health-events module
    - Add Boto3LayerArn parameter to HealthEventsModule stack
    - Pass !Ref Boto3LayerVersion directly (no condition needed)
    - _Requirements: 4.1, 5.1_

- [ ]* 4.5 Write integration tests for health-events module
  - Test module deployment with layer
  - Test Lambda function uses layer boto3 version
  - Test Lambda function maintains existing functionality
  - _Requirements: 4.4, 4.5, 5.3, 5.4, 5.5, 6.1, 6.4, 6.5_

- [ ] 5. Create documentation
  - [x] 5.1 Create README for Lambda layer
    - Document utility script usage
    - Document layer file location
    - Document module integration
    - Add troubleshooting section
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  
  - [x] 5.2 Update main project documentation
    - Add Lambda layer section to data-collection/README.md
    - Document build process
    - Document automatic deployment with Health Events module
    - _Requirements: 7.1, 7.2_

- [x] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The utility script should be tested locally before CloudFormation integration
- The health-events module serves as a reference implementation for other modules
- Layer deploys automatically when Health Events module is enabled - no user configuration needed

