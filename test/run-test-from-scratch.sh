#!/bin/bash
# shellcheck disable=SC2034,SC2086,SC2181
# see ../CONTRIBUTION.md


PREFIX="CID-DC-"
account_id=$(aws sts get-caller-identity --query "Account" --output text)
bucket=cid-$account_id-test
export bucket

# Teardown mode: delete all stacks and clean up
if [ "$1" = "--teardown" ]; then
    echo "Tearing down all CID stacks..."
    BUCKET_NAME="cid-data-${account_id}"

    # Empty data bucket (including versioned objects)
    echo "Emptying bucket $BUCKET_NAME..."
    python3 -c "
import boto3
s3 = boto3.resource('s3')
try:
    s3.Bucket('$BUCKET_NAME').object_versions.delete()
    print('Bucket emptied')
except Exception as e:
    print(f'Bucket cleanup: {e}')
" 2>/dev/null

    # Delete stacks
    for stack in "${PREFIX}SupportCaseSummarizationStack" "${PREFIX}OptimizationDataCollectionStack" "${PREFIX}OptimizationDataReadPermissionsStack"; do
        echo "Deleting $stack..."
        aws cloudformation delete-stack --stack-name "$stack" 2>/dev/null
    done

    # Wait for deletion (retry if DELETE_FAILED)
    for stack in "${PREFIX}SupportCaseSummarizationStack" "${PREFIX}OptimizationDataCollectionStack" "${PREFIX}OptimizationDataReadPermissionsStack"; do
        echo "Waiting for $stack to delete..."
        aws cloudformation wait stack-delete-complete --stack-name "$stack" 2>/dev/null
        # Retry with --retain-resources if stuck
        status=$(aws cloudformation describe-stacks --stack-name "$stack" --query "Stacks[0].StackStatus" --output text 2>/dev/null)
        if [ "$status" = "DELETE_FAILED" ]; then
            echo "$stack DELETE_FAILED, retrying with skip..."
            failed=$(aws cloudformation describe-stack-resources --stack-name "$stack" \
                --query "StackResources[?ResourceStatus=='DELETE_FAILED'].LogicalResourceId" --output text 2>/dev/null)
            aws cloudformation delete-stack --stack-name "$stack" --retain-resources $failed 2>/dev/null
            aws cloudformation wait stack-delete-complete --stack-name "$stack" 2>/dev/null
        fi
        echo "$stack deleted"
    done

    # Clean up Glue database
    echo "Deleting Glue database optimization_data..."
    aws glue delete-database --name optimization_data 2>/dev/null

    echo "Teardown complete"
    exit 0
fi

# build lambda layers
./data-collection/utils/layer-utils/boto3-layer-build.sh

# upload files
./data-collection/utils/upload.sh "$bucket"

# run test
python3 ./test/test_from_scratch.py "$@"
