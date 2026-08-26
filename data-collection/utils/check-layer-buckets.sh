#!/bin/bash
# shellcheck disable=SC2086
# Read-only health check for the LayerBuckets StackSet and the regional code buckets.
#
# For every stack instance it reports:
#   - stack instance status (CURRENT / OUTDATED / FAILED + reason)
#   - the LayerBucket physical bucket and whether it exists in the SAME region
#   - whether the current release artifacts are publicly readable
# It also cross-checks the RegionMap in deploy-data-collection.yaml:
#   - regions in RegionMap without a healthy stack instance (users would fail to deploy)
#   - stack instances not present in RegionMap (dead weight)
#
# Usage:
#   ./check-layer-buckets.sh [--stack-set-name LayerBuckets] [--version vX.Y.Z]
#
# Requires: aws cli, curl, jq. Only read operations are performed.

set -o pipefail

STACK_SET_NAME=LayerBuckets
export AWS_REGION=us-east-1
BUCKET_PREFIX=aws-managed-cost-intelligence-dashboards

code_root=$(git rev-parse --show-toplevel 2>/dev/null)
VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stack-set-name) STACK_SET_NAME="$2"; shift 2;;
    --version)        VERSION="$2"; shift 2;;
    -h|--help)        grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "Unknown option: $1" >&2; exit 1;;
  esac
done

if [[ -z "$VERSION" && -n "$code_root" && -f "$code_root/data-collection/utils/version.json" ]]; then
  VERSION=v$(jq -r '.version' "$code_root/data-collection/utils/version.json")
fi
ARTIFACT="cfn/data-collection/${VERSION}/source/step-functions/main-state-machine.json"

red()    { printf '\033[31m%s\033[0m' "$*"; }
green()  { printf '\033[32m%s\033[0m' "$*"; }
yellow() { printf '\033[33m%s\033[0m' "$*"; }

echo "StackSet: $STACK_SET_NAME (admin region: $AWS_REGION)"
echo "Release version checked: ${VERSION:-<unknown - pass --version>}"
echo

instances=$(aws cloudformation list-stack-instances \
  --stack-set-name "$STACK_SET_NAME" \
  --query 'Summaries[].{account:Account,region:Region,status:StackInstanceStatus.DetailedStatus,reason:StatusReason,stack_id:StackId}' \
  --output json) || { echo "$(red ERROR): cannot list stack instances (check credentials / --stack-set-name)"; exit 1; }

count=$(jq length <<<"$instances")
echo "Stack instances: $count"
printf '%-14s %-16s %-10s %-28s %-10s %s\n' "ACCOUNT" "REGION" "STATUS" "BUCKET REGION (expected=region)" "ARTIFACT" "NOTES"

problems=0
instance_regions=""

for row in $(jq -r '.[] | @base64' <<<"$instances"); do
  _get() { echo "$row" | base64 --decode | jq -r "$1"; }
  account=$(_get .account); region=$(_get .region); status=$(_get .status); reason=$(_get .reason); stack_id=$(_get .stack_id)
  instance_regions+=" $region"

  bucket=""
  if [[ "$stack_id" != "null" && -n "$stack_id" ]]; then
    bucket=$(aws cloudformation list-stack-resources --stack-name "$stack_id" --region "$region" \
      --query 'StackResourceSummaries[?LogicalResourceId==`LayerBucket`].PhysicalResourceId' \
      --output text 2>/dev/null)
  fi
  [[ -z "$bucket" || "$bucket" == "None" ]] && bucket="${BUCKET_PREFIX}-${region}"

  # Where does the bucket actually live? (unauthenticated HEAD is enough)
  actual_region=$(curl -sI "https://${bucket}.s3.amazonaws.com/" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-amz-bucket-region"{print $2}')
  [[ -z "$actual_region" ]] && actual_region="MISSING"

  # Are the release artifacts publicly readable?
  artifact_state="n/a"
  if [[ -n "$VERSION" ]]; then
    http=$(curl -s -o /dev/null -w '%{http_code}' "https://${bucket}.s3.${region}.amazonaws.com/${ARTIFACT}")
    artifact_state=$http
  fi

  notes=""
  ok=1
  [[ "$status" != "SUCCEEDED" && "$status" != "null" ]] && { notes+="instance:$status "; ok=0; }
  if [[ "$actual_region" == "MISSING" ]]; then notes+="bucket-missing "; ok=0;
  elif [[ "$actual_region" != "$region" ]]; then notes+="bucket-in-${actual_region}! "; ok=0; fi
  [[ "$artifact_state" != "200" && "$artifact_state" != "n/a" ]] && { notes+="artifact-HTTP-$artifact_state "; ok=0; }
  [[ $ok -eq 0 ]] && problems=$((problems+1))

  region_disp="$actual_region"; [[ "$actual_region" != "$region" ]] && region_disp=$(red "$actual_region")
  status_disp="$status"; [[ "$status" != "SUCCEEDED" ]] && status_disp=$(red "$status")
  art_disp="$artifact_state"; [[ "$artifact_state" == "200" ]] && art_disp=$(green 200)

  printf '%-14s %-16s %-21s %-39s %-21s %s\n' "$account" "$region" "$status_disp" "$region_disp" "$art_disp" "$notes"
  [[ "$reason" != "null" && -n "$reason" ]] && printf '  %s %s\n' "$(yellow reason:)" "$reason"
done

# Cross-check against RegionMap in the deploy template
if [[ -n "$code_root" && -f "$code_root/data-collection/deploy/deploy-data-collection.yaml" ]]; then
  echo
  mapped=$(awk '/^Mappings:/{m=1} m&&/^  RegionMap:/{r=1;next} r&&/^  [A-Za-z]/{exit} r&&/CodeBucket/{gsub(":","",$1);print $1}' \
    "$code_root/data-collection/deploy/deploy-data-collection.yaml")
  for r in $mapped; do
    if ! grep -qw "$r" <<<"$instance_regions"; then
      echo "$(red WARN): region '$r' is in RegionMap but has NO stack instance — deployments there will fail"
      problems=$((problems+1))
    fi
  done
  for r in $instance_regions; do
    if ! grep -qw "$r" <<<"$mapped"; then
      echo "$(yellow NOTE): stack instance in '$r' is not referenced by RegionMap"
    fi
  done
fi

echo
if [[ $problems -eq 0 ]]; then
  echo "$(green OK): all stack instances healthy, buckets in correct regions, artifacts published."
else
  echo "$(red "$problems problem(s) found.")"
  exit 2
fi
