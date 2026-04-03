#!/bin/bash
# Diagnostic script for CID data collection test failures
# Checks CloudFormation stacks, Step Function executions, and Lambda errors

set -o pipefail

PREFIX="CID-DC-"
REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
LOOKBACK_MINS=${1:-60}  # default 60 minutes, override with first arg

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}=== CID Data Collection Diagnostics ===${NC}"
echo "Account: $ACCOUNT_ID | Region: $REGION | Lookback: ${LOOKBACK_MINS}m"
echo ""

# 1. Check CloudFormation stack status
echo -e "${CYAN}--- CloudFormation Stacks ---${NC}"
for stack in "${PREFIX}OptimizationDataReadPermissionsStack" "${PREFIX}OptimizationDataCollectionStack" "${PREFIX}SupportCaseSummarizationStack"; do
    status=$(aws cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].StackStatus" --output text 2>/dev/null)
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ $stack: NOT FOUND${NC}"
    elif [[ "$status" == *"COMPLETE"* ]] && [[ "$status" != *"ROLLBACK"* ]]; then
        echo -e "${GREEN}✓ $stack: $status${NC}"
    else
        echo -e "${RED}✗ $stack: $status${NC}"
        echo "  Failed resources:"
        aws cloudformation describe-stack-events --stack-name "$stack" \
            --query "StackEvents[?ResourceStatus=='CREATE_FAILED' || ResourceStatus=='UPDATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" \
            --output table 2>/dev/null | head -20
    fi
done

# Check nested stacks
echo ""
echo -e "${CYAN}--- Nested Stack Status ---${NC}"
aws cloudformation describe-stack-resources \
    --stack-name "${PREFIX}OptimizationDataCollectionStack" \
    --query "StackResources[?ResourceType=='AWS::CloudFormation::Stack'].[LogicalResourceId,ResourceStatus]" \
    --output table 2>/dev/null


# 2. Check Step Function executions
echo ""
echo -e "${CYAN}--- Step Function Executions (last ${LOOKBACK_MINS}m) ---${NC}"

SINCE=$(date -u -v-${LOOKBACK_MINS}M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "${LOOKBACK_MINS} minutes ago" +%Y-%m-%dT%H:%M:%SZ)

state_machines=$(aws stepfunctions list-state-machines \
    --query "stateMachines[?starts_with(name, '${PREFIX}')].stateMachineArn" \
    --output text 2>/dev/null)

failed_sms=()
succeeded_count=0
failed_count=0
no_exec_count=0

for sm_arn in $state_machines; do
    sm_name=$(echo "$sm_arn" | awk -F: '{print $NF}')

    # Get most recent execution
    last_exec=$(aws stepfunctions list-executions \
        --state-machine-arn "$sm_arn" \
        --max-results 1 \
        --query "executions[0].[executionArn,status,startDate,stopDate]" \
        --output text 2>/dev/null)

    if [ "$last_exec" = "None" ] || [ -z "$last_exec" ]; then
        echo -e "${YELLOW}? $sm_name: NO EXECUTIONS${NC}"
        no_exec_count=$((no_exec_count + 1))
        continue
    fi

    exec_arn=$(echo "$last_exec" | awk '{print $1}')
    exec_status=$(echo "$last_exec" | awk '{print $2}')

    if [ "$exec_status" = "SUCCEEDED" ]; then
        succeeded_count=$((succeeded_count + 1))
    elif [ "$exec_status" = "FAILED" ]; then
        failed_count=$((failed_count + 1))
        failed_sms+=("$exec_arn")
        echo -e "${RED}✗ $sm_name: FAILED${NC}"

        # Get failure cause
        exec_detail=$(aws stepfunctions describe-execution \
            --execution-arn "$exec_arn" \
            --query "[error,cause]" \
            --output text 2>/dev/null)
        if [ -n "$exec_detail" ] && [ "$exec_detail" != "None	None" ]; then
            echo "  Error: $(echo "$exec_detail" | head -c 300)"
        fi

        # Get failed step from execution history
        failed_event=$(aws stepfunctions get-execution-history \
            --execution-arn "$exec_arn" \
            --reverse-order \
            --max-results 10 \
            --query "events[?type=='TaskFailed' || type=='ExecutionFailed' || type=='LambdaFunctionFailed'].[type,taskFailedEventDetails.error,taskFailedEventDetails.cause]" \
            --output text 2>/dev/null | head -5)
        if [ -n "$failed_event" ]; then
            echo "  History: $(echo "$failed_event" | head -c 300)"
        fi
    elif [ "$exec_status" = "RUNNING" ]; then
        echo -e "${YELLOW}⟳ $sm_name: RUNNING${NC}"
    else
        echo -e "${YELLOW}? $sm_name: $exec_status${NC}"
    fi
done

echo ""
echo -e "Summary: ${GREEN}${succeeded_count} succeeded${NC}, ${RED}${failed_count} failed${NC}, ${YELLOW}${no_exec_count} no executions${NC}"


# 3. Check Lambda errors in CloudWatch
echo ""
echo -e "${CYAN}--- Lambda Errors (last ${LOOKBACK_MINS}m) ---${NC}"

START_MS=$(python3 -c "import time; print(int((time.time() - ${LOOKBACK_MINS}*60) * 1000))")
END_MS=$(python3 -c "import time; print(int(time.time() * 1000))")

lambda_functions=$(aws lambda list-functions \
    --query "Functions[?starts_with(FunctionName, '${PREFIX}')].FunctionName" \
    --output text 2>/dev/null)

error_count=0
for func in $lambda_functions; do
    log_group="/aws/lambda/$func"

    # Check if log group exists
    aws logs describe-log-groups --log-group-name-prefix "$log_group" --query "logGroups[0].logGroupName" --output text 2>/dev/null | grep -q "$log_group" || continue

    # Search for errors
    errors=$(aws logs filter-log-events \
        --log-group-name "$log_group" \
        --start-time "$START_MS" \
        --end-time "$END_MS" \
        --filter-pattern "?ERROR ?Exception ?Traceback ?\"Task timed out\"" \
        --max-items 5 \
        --query "events[].[message]" \
        --output text 2>/dev/null)

    if [ -n "$errors" ]; then
        error_count=$((error_count + 1))
        echo -e "${RED}✗ $func:${NC}"
        echo "$errors" | head -c 500
        echo ""
    fi
done

if [ $error_count -eq 0 ]; then
    echo -e "${GREEN}No Lambda errors found${NC}"
fi

# 4. Check Glue Crawlers
echo ""
echo -e "${CYAN}--- Glue Crawlers ---${NC}"

crawlers=$(aws glue get-crawlers \
    --query "Crawlers[?starts_with(Name, '${PREFIX}')].[Name,State,LastCrawl.Status,LastCrawl.ErrorMessage]" \
    --output text 2>/dev/null)

if [ -n "$crawlers" ]; then
    while IFS=$'\t' read -r name state status error_msg; do
        if [ "$status" = "SUCCEEDED" ]; then
            echo -e "${GREEN}✓ $name: $state (last run: $status)${NC}"
        elif [ -n "$status" ]; then
            echo -e "${RED}✗ $name: $state (last run: $status)${NC}"
            [ "$error_msg" != "None" ] && echo "  Error: $error_msg"
        else
            echo -e "${YELLOW}? $name: $state (never run)${NC}"
        fi
    done <<< "$crawlers"
else
    echo -e "${YELLOW}No CID crawlers found${NC}"
fi

# 5. Check S3 data bucket contents
echo ""
echo -e "${CYAN}--- S3 Data Bucket ---${NC}"
BUCKET="cid-data-${ACCOUNT_ID}"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    echo -e "${GREEN}✓ Bucket exists: $BUCKET${NC}"
    echo "Top-level prefixes with data:"
    aws s3api list-objects-v2 --bucket "$BUCKET" --delimiter "/" \
        --query "CommonPrefixes[].Prefix" --output text 2>/dev/null | tr '\t' '\n' | head -20
else
    echo -e "${RED}✗ Bucket not found: $BUCKET${NC}"
fi

echo ""
echo -e "${CYAN}=== Diagnostics Complete ===${NC}"
