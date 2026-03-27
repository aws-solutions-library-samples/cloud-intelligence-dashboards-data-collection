#!/bin/bash
# This script builds and publishes the boto3 Lambda layer to all regional buckets.
# It should be run as part of the release process.
#
# Usage: ./boto3-layer-publish.sh
#
# Prerequisites:
# - AWS CLI configured with appropriate credentials
# - LayerBuckets CloudFormation StackSet deployed
# - Access to the central bucket (aws-managed-cost-intelligence-dashboards)

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print error messages
error() {
    echo -e "${RED}ERROR: $1${NC}" >&2
}

# Function to print success messages
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print info messages
info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Get git root and navigate to script directory
git_root=$(git rev-parse --show-toplevel)
cd "${git_root}/data-collection/deploy/layers/" || exit

# Get version from version.json
version=$(jq -r '.version' "${git_root}/data-collection/utils/version.json")
if [ -z "$version" ]; then
    error "Failed to read version from version.json"
    exit 1
fi

info "Building boto3 layer for version: $version"

# Build the layer using the build script in the same directory
layer_file=$(bash "./boto3-layer-build.sh" 2>&1 | tail -1)

# Check if build was successful
if [ ! -f "./boto3-layer.zip" ]; then
    error "Layer build failed - boto3-layer.zip not found"
    exit 1
fi

layer_file="boto3-layer.zip"
success "Layer built successfully: $layer_file"

# Get layer size
layer_size=$(du -h "$layer_file" | cut -f1)
info "Layer size: $layer_size"

# Configuration
export AWS_REGION=us-east-1
export STACK_SET_NAME=LayerBuckets
export CENTRAL_BUCKET=aws-managed-cost-intelligence-dashboards

# Upload to central bucket
info "Uploading to central bucket: $CENTRAL_BUCKET"

# Upload to versioned path
aws s3 cp "$layer_file" "s3://$CENTRAL_BUCKET/cfn/data-collection/v${version}/layers/boto3-layer.zip" || {
    error "Failed to upload to central bucket"
    exit 1
}

success "Uploaded to central bucket: s3://$CENTRAL_BUCKET/cfn/data-collection/v${version}/layers/boto3-layer.zip"

# Upload to regional buckets
info "Uploading to regional buckets..."

upload_count=0
error_count=0

aws cloudformation list-stack-instances \
  --stack-set-name "$STACK_SET_NAME" \
  --query 'Summaries[].[StackId,Region]' \
  --output text |
  while read -r stack_id region; do
    info "Uploading to region: $region"
    
    # Get the bucket name for this region
    bucket=$(aws cloudformation list-stack-resources --stack-name "$stack_id" \
      --query 'StackResourceSummaries[?LogicalResourceId == `LayerBucket`].PhysicalResourceId' \
      --region "$region" --output text)
    
    if [ -z "$bucket" ]; then
        error "Failed to get bucket name for region $region"
        error_count=$((error_count + 1))
        continue
    fi
    
    # Upload to versioned path
    output=$(aws s3 cp "$layer_file" \
      "s3://$bucket/cfn/data-collection/v${version}/layers/boto3-layer.zip" \
      --region "$region" 2>&1)
    
    # shellcheck disable=SC2181
    if [ $? -ne 0 ]; then
        error "Failed to upload to $region: $output"
        error_count=$((error_count + 1))
    else
        success "Uploaded to $region: s3://$bucket/cfn/data-collection/v${version}/layers/boto3-layer.zip"
        upload_count=$((upload_count + 1))
    fi
  done

# Cleanup
info "Cleaning up local layer file..."
rm -f "$layer_file"
success "Cleanup completed"

# Summary
echo ""
echo "=========================================="
echo "Boto3 Layer Publish Summary"
echo "=========================================="
echo "Version:           v${version}"
echo "Layer size:        $layer_size"
echo "Successful uploads: $upload_count regions"
if [ $error_count -gt 0 ]; then
    echo -e "${RED}Failed uploads:     $error_count regions${NC}"
fi
echo "=========================================="
echo ""

if [ $error_count -gt 0 ]; then
    error "Some uploads failed. Please review the errors above."
    exit 1
fi

success "Boto3 layer published successfully to all regions!"
echo ""
info "The layer is now available at:"
echo "  s3://REGIONAL-BUCKET/cfn/data-collection/v${version}/layers/boto3-layer.zip"
echo ""

exit 0
