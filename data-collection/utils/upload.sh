#!/bin/bash
# shellcheck disable=SC2086
# This script uploads CloudFormation files to S3 bucket. Can be used with any testing bucket or prod.
# see also README.md

if [ -n "$1" ]; then
  bucket=$1
else
  echo "ERROR: First parameter not supplied. Provide a bucket name."
  exit 1
fi
code_path=$(git rev-parse --show-toplevel)/data-collection/deploy
version=$(jq -r '.version' data-collection/utils/version.json)

# The boto3 layer zip is gitignored and not rebuilt here; refuse to publish a missing or stale one.
min_botocore=$(grep -oE '^MIN_BOTOCORE_VERSION="[0-9.]+"' "$(dirname "$0")/layer-utils/boto3-layer-build.sh" | cut -d'"' -f2)
layer_zip=$code_path/layers/boto3-layer.zip
layer_botocore=$(unzip -p "$layer_zip" python/botocore/__init__.py 2>/dev/null | grep -oE "^__version__ = '[0-9.]+'" | cut -d"'" -f2)
if [ -z "$layer_botocore" ] || ! python3 -c "import sys; v=lambda s: tuple(int(p) for p in s.split('.')[:3]); sys.exit(0 if v('$layer_botocore') >= v('$min_botocore') else 1)"; then
  echo "ERROR: $layer_zip has botocore '${layer_botocore:-missing}', need >= $min_botocore."
  echo "Run ./data-collection/utils/layer-utils/boto3-layer-build.sh first."
  exit 1
fi
echo "boto3 layer: botocore $layer_botocore"

echo "Sync to $bucket"
aws s3 sync $code_path/       s3://$bucket/cfn/data-collection/v$version/ --delete
echo 'Done'
