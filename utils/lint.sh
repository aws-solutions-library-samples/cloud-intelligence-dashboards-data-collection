#!/bin/bash
# shellcheck disable=SC2086,SC2181
# This script runs cfn-lint cfn_nag_scan and checkov for all templates in folder

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

folder=$(git rev-parse --show-toplevel)
success_count=0
failure_count=0

# CKV_AWS_18 - Ensure AWS access logging is enabled on S3 buckets - Public is not publically shared, and access is limited to QS and account Admins thus logging is not required. Also avoid additional costs. 
# CKV_AWS_116 - Ensure the S3 bucket has logging enabled - Public is not publically shared, and access is limited to QS and account Admins thus logging is not required. Also avoid additional costs. 
# CKV_AWS_117 - Ensure AWS Lambda function is configured inside a VPC - Not requied for Lambda functionality as only AWS API calls are used. 
# CKV_AWS_173 - Check encryption settings for Lambda environmental variable - No sensitive parameters in environmental variables
# CKV_AWS_195 - Ensure Glue component has a security configuration associated - AWS managed encryption is used for s3.
# CKV_SECRET_6 - Base64 High Entropy String - Remove false positives
# CKV_AWS_115 - Ensure that AWS Lambda function is configured for function-level concurrent execution limit - No need for concurency reservation
# CKV_AWS_158 - Ensure that CloudWatch Log Group is encrypted by KMS - No need as there no sesible information in the logs
checkov_skip=CKV_AWS_18,CKV_AWS_117,CKV_AWS_116,CKV_AWS_173,CKV_AWS_195,CKV_SECRET_6,CKV_AWS_115,CKV_AWS_158

export exclude_files=("module-inventory.yaml" "module-pricing.yaml" "module-backup.yaml" "module-kiro-user-activity.yaml") # For::Each breaks lint :'(

yaml_files=$(find "$folder" -type f -name "*.yaml" -exec ls -1t "{}" +;) # ordered by date

for file in $yaml_files; do
    echo "Linting $(basename $file)"
    fail=0

    # checkov
    output=$(eval checkov  --skip-download --skip-check $checkov_skip --quiet -f "$file")
    if [ $? -ne 0 ]; then
        echo "$output" | awk '{ print "\t" $0 }'
        echo -e "checkov      ${RED}KO${NC}"  | awk '{ print "\t" $0 }'
        fail=1
    else
        echo -e "checkov      ${GREEN}OK${NC}"  | awk '{ print "\t" $0 }'
    fi

    # cfn-lint
    output=$(eval cfn-lint -- "$file")
    if [ $? -ne 0 ]; then
        echo "$output" | awk '{ print "\t" $0 }'
        echo -e "cfn-lint     ${RED}KO${NC}"  | awk '{ print "\t" $0 }'
        fail=1
    else
        echo -e "cfn-lint     ${GREEN}OK${NC}"  | awk '{ print "\t" $0 }'
    fi

    if [ "$(basename $file)" == "${exclude_files[0]}" ] || [ "$(basename $file)" == "${exclude_files[1]}" ] || [ "$(basename $file)" == "${exclude_files[2]}" ]; then
        echo -e "cfn_nag_scan ${YELLOW}SKIP${NC} For::Each breaks cfn_nag"  | awk '{ print "\t" $0 }'
        continue
    fi


    # cfn_nag_scan
    output=$(eval cfn_nag_scan --input-path "$file")
    if [ $? -ne 0 ]; then
        echo "$output" | awk '{ print "\t" $0 }'
        echo -e "cfn_nag_scan ${RED}KO${NC}"  | awk '{ print "\t" $0 }'
        fail=1
    else
        echo -e "cfn_nag_scan ${GREEN}OK${NC}"  | awk '{ print "\t" $0 }'
    fi

    if [ $fail -ne 0 ]; then
        ((failure_count++))
    else
        ((success_count++))
    fi
done

echo "Successful lints: $success_count"
echo "Failed lints:     $failure_count"
if [ $failure_count -ne 0 ]; then
    exit 1
else
    exit 0
fi
