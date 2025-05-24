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

echo "Sync to $bucket"
#aws s3 sync $code_path/       s3://$bucket/cfn/data-collection/ --delete
aws s3 sync $code_path/       s3://$bucket/cfn/data-collection/v$version/ --delete
echo 'Done'
