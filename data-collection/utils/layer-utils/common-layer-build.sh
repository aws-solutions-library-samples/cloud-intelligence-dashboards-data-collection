#!/bin/bash

# Build script for the CID common Lambda layer.
# Packages data-collection/deploy/source/common as python/common/ so module
# Lambdas can `from common.module import DataCollectionModule`.
#
# Usage: ./common-layer-build.sh
#
# Output: data-collection/deploy/layers/common-layer.zip
#         (synced to the CFN bucket by data-collection/utils/upload.sh)

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SOURCE_DIR="$PROJECT_ROOT/data-collection/deploy/source/common"
TMP_DIR="$PROJECT_ROOT/.tmp/common-layer"
OUTPUT_DIR="$PROJECT_ROOT/data-collection/deploy/layers"
OUTPUT_FILE="common-layer.zip"

if ! command -v zip &> /dev/null; then
    echo "ERROR: zip command not found. Install the zip utility." >&2
    exit 1
fi

VERSION=$(python3 -c "import ast,sys; t=ast.parse(open(sys.argv[1]).read()); print(next(n.value.value for n in t.body if isinstance(n, ast.Assign) and n.targets[0].id == '__version__'))" "$SOURCE_DIR/__init__.py")

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR/python/common" "$OUTPUT_DIR"
cp "$SOURCE_DIR"/*.py "$TMP_DIR/python/common/"

# Fail the build rather than ship a layer that does not compile
python3 -m py_compile "$TMP_DIR"/python/common/*.py
find "$TMP_DIR" -type d -name "__pycache__" -exec rm -rf {} +

rm -f "$OUTPUT_DIR/$OUTPUT_FILE"
(cd "$TMP_DIR" && zip -r -q "$OUTPUT_DIR/$OUTPUT_FILE" python/)
rm -rf "$TMP_DIR"

echo "Built $OUTPUT_DIR/$OUTPUT_FILE (common layer v$VERSION)"
