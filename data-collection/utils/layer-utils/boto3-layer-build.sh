#!/bin/bash

# Build script for AWS Lambda Layer containing boto3 and botocore
# This script creates a Lambda layer package with the correct directory structure
# for Python 3.13 runtime.
#
# Usage: ./boto3-layer-build.sh
#
# Output: data-collection/deploy/layers/boto3-layer.zip
# Location: data-collection/utils/layer-utils/
# shellcheck disable=SC2016,SC2086,SC2162,SC2030,SC2031

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TMP_DIR="$PROJECT_ROOT/.tmp"
OUTPUT_DIR="$PROJECT_ROOT/data-collection/deploy/layers"
OUTPUT_FILE="boto3-layer.zip"

# Function to print error messages
error() {
    echo -e "${RED}ERROR: $1${NC}" >&2
    if [ -n "$2" ]; then
        echo "Details: $2" >&2
    fi
    if [ -n "$3" ]; then
        echo "Suggestion: $3" >&2
    fi
}

# Function to print success messages
success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print info messages
info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    error "pip3 not found" "pip3 is required to install packages" "Install Python 3 and pip3"
    exit 1
fi

# Check if zip is available
if ! command -v zip &> /dev/null; then
    error "zip command not found" "zip utility is required to create the layer package" "Install zip utility (e.g., apt-get install zip)"
    exit 1
fi

info "Starting Lambda layer build process..."
info "Configuration:"
echo "  - Python runtimes: All compatible (version-agnostic)"
echo "  - Project root: $PROJECT_ROOT"
echo "  - Output: $OUTPUT_DIR/$OUTPUT_FILE"
echo ""

# Clean up any existing temporary directory
if [ -d "$TMP_DIR" ]; then
    info "Cleaning up existing temporary directory..."
    rm -rf "$TMP_DIR"
fi

# Create temporary build directory structure
LAYER_DIR="$TMP_DIR/python"
info "Creating directory structure: .tmp/python/"
mkdir -p "$LAYER_DIR" || {
    error "Failed to create layer directory structure" "Path: $LAYER_DIR" "Check disk space and permissions"
    exit 3
}

success "Directory structure created"

# Install boto3 with pip
info "Installing latest boto3 and dependencies..."

pip3 install boto3 --target "$LAYER_DIR" --upgrade --quiet || {
    error "Failed to install boto3" "pip3 install failed" "Check network connectivity and Python version compatibility"
    exit 1
}

success "boto3 installed successfully"

# Detect installed versions
info "Detecting installed package versions..."
INSTALLED_BOTO3_VERSION=$(python3 -c "import sys; sys.path.insert(0, '$LAYER_DIR'); import boto3; print(boto3.__version__)" 2>/dev/null || echo "unknown")
INSTALLED_BOTOCORE_VERSION=$(python3 -c "import sys; sys.path.insert(0, '$LAYER_DIR'); import botocore; print(botocore.__version__)" 2>/dev/null || echo "unknown")

if [ "$INSTALLED_BOTO3_VERSION" = "unknown" ] || [ "$INSTALLED_BOTOCORE_VERSION" = "unknown" ]; then
    error "Failed to detect package versions" "Could not import boto3 or botocore" "Verify installation succeeded"
    exit 5
fi

success "Detected versions:"
echo "  - boto3: $INSTALLED_BOTO3_VERSION"
echo "  - botocore: $INSTALLED_BOTOCORE_VERSION"

# Clean up unnecessary files
info "Cleaning up unnecessary files..."

# Remove .pyc files
find "$LAYER_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$LAYER_DIR" -type f -name "*.pyo" -delete 2>/dev/null || true

# Remove __pycache__ directories
find "$LAYER_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Remove .dist-info directories
find "$LAYER_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

success "Cleanup completed"

# Validate package structure
info "Validating package structure..."

VALIDATION_ERRORS=0

# Check if python directory exists
if [ ! -d "$TMP_DIR/python" ]; then
    error "Validation failed" "Missing python/ directory" ""
    VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

# Check if boto3 package exists
if [ ! -d "$LAYER_DIR/boto3" ]; then
    error "Validation failed" "Missing boto3 package directory" ""
    VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

# Check if boto3 __init__.py exists
if [ ! -f "$LAYER_DIR/boto3/__init__.py" ]; then
    error "Validation failed" "Missing boto3/__init__.py" ""
    VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

# Check if botocore package exists
if [ ! -d "$LAYER_DIR/botocore" ]; then
    error "Validation failed" "Missing botocore package directory" ""
    VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

# Check if botocore __init__.py exists
if [ ! -f "$LAYER_DIR/botocore/__init__.py" ]; then
    error "Validation failed" "Missing botocore/__init__.py" ""
    VALIDATION_ERRORS=$((VALIDATION_ERRORS + 1))
fi

if [ $VALIDATION_ERRORS -gt 0 ]; then
    error "Package validation failed" "$VALIDATION_ERRORS error(s) found" "Review build logs and verify pip installation"
    exit 5
fi

success "Package structure validated"

# Create output directory if it doesn't exist
if [ ! -d "$OUTPUT_DIR" ]; then
    info "Creating output directory: $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR" || {
        error "Failed to create output directory" "Directory: $OUTPUT_DIR" "Check directory permissions"
        exit 3
    }
fi

# Create zip file
OUTPUT_PATH="$OUTPUT_DIR/$OUTPUT_FILE"
info "Creating zip file: $OUTPUT_PATH"

# Change to temp directory to ensure correct zip structure
cd "$TMP_DIR" || {
    error "Failed to change to temp directory" "Directory: $TMP_DIR" ""
    exit 4
}

# Create zip with python/ at the root
zip -r -q "$OUTPUT_PATH" python/ || {
    error "Failed to create zip file" "Output: $OUTPUT_PATH" "Check output directory permissions and disk space"
    exit 4
}

# Return to original directory
cd - > /dev/null

# Verify zip was created and is non-empty
if [ ! -s "$OUTPUT_PATH" ]; then
    error "Zip file is missing or empty" "Output: $OUTPUT_PATH" "Check disk space and permissions"
    rm -rf "$TMP_DIR"
    exit 4
fi

success "Zip file created successfully"

# Get zip file size
if command -v stat &> /dev/null; then
    # Try macOS stat format first, then Linux format
    ZIP_SIZE_BYTES=$(stat -f%z "$OUTPUT_PATH" 2>/dev/null || stat -c%s "$OUTPUT_PATH" 2>/dev/null || echo "0")
else
    ZIP_SIZE_BYTES="0"
fi

if command -v du &> /dev/null; then
    ZIP_SIZE=$(du -h "$OUTPUT_PATH" | cut -f1)
else
    ZIP_SIZE="unknown"
fi

# Check if size exceeds Lambda layer limit (50 MB compressed)
MAX_COMPRESSED_SIZE=$((50 * 1024 * 1024))  # 50 MB in bytes
if [ "$ZIP_SIZE_BYTES" != "0" ] && [ "$ZIP_SIZE_BYTES" -gt "$MAX_COMPRESSED_SIZE" ]; then
    error "Warning: Zip file exceeds recommended size" "Size: $ZIP_SIZE" "Lambda layers have a 50 MB compressed size limit"
fi

# Clean up temporary directory
info "Cleaning up temporary directory..."
rm -rf "$TMP_DIR"
success "Cleanup completed"

# Display summary
echo ""
echo "=========================================="
echo "Lambda Layer Build Summary"
echo "=========================================="
echo "Output file:      $OUTPUT_PATH"
echo "File size:        $ZIP_SIZE"
echo "boto3 version:    $INSTALLED_BOTO3_VERSION"
echo "botocore version: $INSTALLED_BOTOCORE_VERSION"
echo "Python runtimes:  All compatible (version-agnostic)"
echo "=========================================="
echo ""

success "Lambda layer package built successfully!"


# Output the filename for scripting (like case-summarization does)
echo "$OUTPUT_FILE" >&2

exit 0
