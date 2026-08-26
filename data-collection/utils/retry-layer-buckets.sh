#!/bin/bash
# retry-layer-buckets.sh — (re)create LayerBuckets stack instances, retrying while S3
# releases the bucket names (after deleting misplaced buckets with the same names).
#
# Retries ONLY the "bucket AlreadyExists" failure (S3 global name-release lag).
# Any other failure stops the script for manual inspection.
#
# Prerequisites (manual, before running):
#   - failed stack instances for the target regions deleted
#   - misplaced us-east-1 buckets deleted
#
# Usage: ./retry-layer-buckets.sh <region> [region ...]

STACK_SET=LayerBuckets
ACCOUNT=223485597511
ADMIN_REGION=us-east-1
CALL_AS=""          # set to "--call-as DELEGATED_ADMIN" if needed for your creds
SLEEP=60            # pause between rounds
MAX_ROUNDS=60       # give up after ~1h

REGIONS="$*"
if [[ -z "$REGIONS" ]]; then
  echo "Usage: $0 <region> [region ...]" >&2
  exit 1
fi

wait_for_ops() {
  while true; do
    running=$(aws cloudformation list-stack-set-operations --stack-set-name $STACK_SET \
      --region $ADMIN_REGION $CALL_AS \
      --query 'Summaries[?Status==`RUNNING`||Status==`STOPPING`||Status==`QUEUED`]|length(@)' --output text)
    [[ "$running" == "0" ]] && break
    echo "  waiting for running stack-set operation..."; sleep 20
  done
}

pending="$REGIONS"
round=0
while [[ -n "$pending" && $round -lt $MAX_ROUNDS ]]; do
  round=$((round+1))
  echo "=== Round $round — attempting: $pending ==="

  # all regions in parallel within one operation; FailureTolerancePercentage=100
  # so one region's (expected, retryable) failure does not cancel the others
  wait_for_ops
  aws cloudformation create-stack-instances --stack-set-name $STACK_SET \
    --accounts $ACCOUNT --regions $pending --region $ADMIN_REGION $CALL_AS \
    --operation-preferences RegionConcurrencyType=PARALLEL,FailureTolerancePercentage=100 \
    --query OperationId --output text
  wait_for_ops

  still_pending=""
  for r in $pending; do
    status=$(aws cloudformation list-stack-instances --stack-set-name $STACK_SET \
      --region $ADMIN_REGION $CALL_AS \
      --query "Summaries[?Region=='$r'].StackInstanceStatus.DetailedStatus" --output text)
    reason=$(aws cloudformation list-stack-instances --stack-set-name $STACK_SET \
      --region $ADMIN_REGION $CALL_AS \
      --query "Summaries[?Region=='$r'].StatusReason" --output text)

    if [[ "$status" == "SUCCEEDED" ]]; then
      echo "  $r: SUCCEEDED"
    elif echo "$reason" | grep -qE "AlreadyExists|conflicting conditional operation|OperationAborted|failure tolerance"; then
      # 'failure tolerance' = cancelled because another region in the same operation
      # failed; this region was never attempted, so it is safe to retry
      echo "  $r: name not released yet ($(echo "$reason" | grep -oE 'AlreadyExists|conflicting conditional operation|OperationAborted|failure tolerance' | head -1)) — will retry"
      still_pending+=" $r"
    else
      echo "  $r: FAILED with unexpected reason — stopping."
      echo "  Reason: $reason"
      exit 1
    fi
  done

  # remove all failed instances in one parallel operation before the next round
  if [[ -n "$still_pending" ]]; then
    aws cloudformation delete-stack-instances --stack-set-name $STACK_SET \
      --accounts $ACCOUNT --regions $still_pending --no-retain-stacks \
      --operation-preferences RegionConcurrencyType=PARALLEL,FailureTolerancePercentage=100 \
      --region $ADMIN_REGION $CALL_AS --query OperationId --output text
    wait_for_ops
  fi

  pending=$(echo $still_pending)
  [[ -n "$pending" ]] && { echo "  sleeping ${SLEEP}s before next round..."; sleep $SLEEP; }
done

if [[ -z "$pending" ]]; then
  echo "=== All instances created successfully ==="
  echo "Next: run release.sh, then check-layer-buckets.sh to verify artifacts."
else
  echo "=== GAVE UP after $MAX_ROUNDS rounds; still pending: $pending ==="
  echo "Check who holds the bucket name(s):"
  for r in $pending; do
    printf '%s: ' "$r"
    curl -sI "https://aws-managed-cost-intelligence-dashboards-$r.s3.amazonaws.com/" \
      | tr -d '\r' | awk -F': ' 'tolower($1)=="x-amz-bucket-region"{print $2}'
  done
  exit 2
fi
