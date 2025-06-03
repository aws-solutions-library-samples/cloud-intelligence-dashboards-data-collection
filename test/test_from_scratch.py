"""
# Integration test for Cost Optimization Data Collection

## About
    This test will:
    - deploy Cost Optimization Data Collection stacks (all in one account)
    - update all nested stacks to the git version
    - trigger collection
    - test that collection works  (tables are not empty)
    - delete all stacks and tables

## Prerequisites in account:
    1. Activate Organizations
    2. Opt-In Compute Optimizer
    3. Activate Business or Enterprise Support (for ta collection only)
    4. Create:
        RDS instance, Budget, Unattached EBS, ECS cluster with at least 1 Service,
    FIXME: add CFM for Prerequisites

## Install:
    pip3 install cfn-flip boto3 pytest

## Run (expect 15 mins):
Pytest:

    pytest

Python:
    python3 Test/test-from-scratch.py


"""
import logging
import sys
import json
import time

import pytest
import boto3

from utils import athena_query

from utils import create_case, trigger_collection, get_case_data, clean_bucket

logger = logging.getLogger(__name__)
region = boto3.session.Session().region_name
account_id = boto3.client('sts').get_caller_identity()['Account']
version = json.load(open('data-collection/utils/version.json'))['version']

COLLECTION_BUCKET =  f'cid-data-{account_id}'

def test_deployment_works(athena):
    pass

def test_budgets_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."budgets_data" LIMIT 10;')
    assert len(data) > 0, 'budgets_data is empty'


def test_cost_explorer_rightsizing_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."cost_explorer_rightsizing_data" LIMIT 10;')
    assert len(data) > 0, 'cost_explorer_rightsizing_data is empty'


def test_cost_anomaly_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."cost_anomaly_data" LIMIT 10;')
    assert len(data) > 0, 'cost_anomaly_data is empty'

def test_support_cases_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."support_cases_data" LIMIT 10;')
    assert len(data) > 0, 'support_cases_data is empty'

def test_support_cases_communications(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."support_cases_communications" LIMIT 10;')
    assert len(data) > 0, 'support_cases_communications is empty'

def test_support_cases_status(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."support_cases_status" LIMIT 10;')
    assert len(data) > 0, 'test_support_cases_status is empty'

def test_ecs_chargeback_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."ecs_chargeback_data" LIMIT 10;')
    assert len(data) > 0, 'ecs_chargeback_data is empty'

def test_inventory_workspaces_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_workspaces_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_workspaces_data is empty'

def test_inventory_ami_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_ami_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_ami_data is empty'

def test_inventory_ebs_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_ebs_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_ebs_data is empty'

def test_inventory_snapshot_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_snapshot_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_snapshot_data is empty'

def test_inventory_ec2_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_ec2_instances_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_ec2_data is empty'

def test_inventory_vpc_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_vpc_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_vpc_data is empty'

def test_inventory_rds_snapshot_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_rds_db_snapshots_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_rds_db_snapshots_data is empty'

def test_inventory_lambda_functions_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_lambda_functions_data" LIMIT 10;')
    assert len(data) > 0, 'inventory_lambda_functions_data is empty'

def test_inventory_network_interfaces_functions_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_network_interfaces_data" LIMIT 10;')
    assert len(data) > 0, 'inventory-network-interfaces-data'

def test_rds_usage_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."rds_usage_data" LIMIT 10;')
    assert len(data) > 0, 'rds_usage_data is empty'

def test_organizations_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."organization_data" LIMIT 10;')
    assert len(data) > 0, 'organizations_data is empty'

def test_trusted_advisor_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."trusted_advisor_data" LIMIT 10;')
    assert len(data) > 0, 'trusted_advisor_data is empty'

def test_workspaces_metrics_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."workspaces_metrics_data" LIMIT 10;')
    assert len(data) > 0, 'workspaces_metrics_data is empty'

def test_transit_gateway_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."transit_gateway_data" LIMIT 10;')
    assert len(data) > 0, 'transit_gateway_data is empty'


def test_opensearch_domains_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_opensearch_domains_data" LIMIT 10;')
    assert len(data) > 0, 'opensearch_domains_data is empty'


def test_elasticache_clusters_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_elasticache_clusters_data" LIMIT 10;')
    assert len(data) > 0, 'elasticache_clusters_data is empty'


def test_rds_db_instances_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."inventory_rds_db_instances_data" LIMIT 10;')
    assert len(data) > 0, 'rds_db_instances_data is empty'

def test_pricing_computesavingsplan_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_computesavingsplan_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_computesavingsplan_data is empty'

def test_pricing_ec2_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_ec2_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_ec2_data is empty'

def test_pricing_elasticache_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_elasticache_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_elasticache_data is empty'

def test_pricing_opensearch_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_opensearch_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_opensearch_data is empty'

def test_pricing_rds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_rds_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_rds_data is empty'

def test_pricing_lambda_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_lambda_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_lambda_data is empty'

def test_pricing_regionnames_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."pricing_regionnames_data" LIMIT 10;')
    assert len(data) > 0, 'pricing_regionnames_data is empty'

def test_compute_optimizer_export_triggered(compute_optimizer, start_time):
    jobs = compute_optimizer.describe_recommendation_export_jobs()['recommendationExportJobs']
    logger.debug(f'Jobs in: {jobs}')
    jobs_since_start = [job for job in jobs if job['creationTimestamp'].replace(tzinfo=None) > start_time.replace(tzinfo=None)]
    assert len(jobs_since_start) == 8, f'started {len(jobs_since_start)} jobs. Expected 8. Not all jobs launched'
    jobs_failed = [job for job in jobs_since_start if job.get('status') == 'failed']
    assert len(jobs_failed) == 0, f'Some jobs failed {jobs_failed}'
    # TODO: check how we can add better test, taking into account 15-30 mins delay of export in CO

def test_health_events_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."health_events_detail_data" LIMIT 10;')
    assert len(data) > 0, 'health_events_detail_data is empty'

def test_license_manager_grants(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."license_manager_grants" LIMIT 10;')
    assert len(data) > 0, 'license_manager_grants is empty'

def test_license_manager_licenses(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."license_manager_licenses" LIMIT 10;')
    assert len(data) > 0, 'license_manager_licenses is empty'

def test_quicksight_users(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."quicksight_user_data" LIMIT 10;')
    assert len(data) > 0, 'quicksight_user_data is empty'

def test_quicksight_groups(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."quicksight_group_data" LIMIT 10;')
    assert len(data) > 0, 'quicksight_group_data is empty'

def test_quicksight_groupmembership(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."quicksight_groupmembership_data" LIMIT 10;')
    assert len(data) > 0, 'quicksight_groupmembership_data is empty'

def test_servicequotas_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."service_quotas_data" LIMIT 10;')
    assert len(data) > 0, 'service_quotas_data is empty'

def test_servicequotas_history(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."service_quotas_history" LIMIT 10;')
    assert len(data) > 0, 'service_quotas_history is empty'

def test_aws_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."aws_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'aws_feeds_data is empty'

def test_hashicorp_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."hashicorp_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'hashicorp_feeds_data is empty'

def test_datadog_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."datadog_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'datadog_feeds_data is empty'

def test_orca_security_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."orca_security_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'orca_security_feeds_data is empty'

def test_wiz_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."wiz_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'wiz_feeds_data is empty'

def test_crowdstrike_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."crowdstrike_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'crowdstrike_feeds_data is empty'

def test_tenable_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."tenable_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'tenable_feeds_data is empty'

def test_databricks_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."databricks_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'databricks_feeds_data is empty'

def test_gitlab_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."gitlab_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'gitlab_feeds_data is empty'

def test_circle_ci_feeds_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."circle_ci_feeds_whats_new" LIMIT 10;')
    assert len(data) > 0, 'circle_ci_feeds_data is empty'

def test_resiliencehub_daily_assessment_data(athena):
    data = athena_query(athena=athena, sql_query='SELECT * FROM "optimization_data"."resiliencehub_daily_assessments" LIMIT 10;')
    assert len(data) > 0, 'resiliencehub_daily_assessments is empty'

def test_content_of_summary_not_empty(s3):
    s3_client = boto3.client('s3')
    case_data = {
        "CaseId": "case-081315907440-muen-2024-1YbOCmcjYqnFivIk",
        "DisplayId": "123123123123", "Subject": "Test Case 123",  "Status": "pending-customer-action",
        "ServiceCode": "amazon-finspace", "CategoryCode": "environment-creation",
        "SeverityCode": "normal",  "SubmittedBy": "john.doe@unicorn-ltd.io",
        "TimeCreated": "2024-09-15T14:32:18.923Z",
        "CCEmailAddresses": [
            "finops@unicorn-ltd.io"
        ],
        "Language": "en",
        "Summary": "",
        "AccountAlias": "Unicorn Analytics Platform"
    }
    case_communications = [
        {
            "CaseId": "case-081315907440-muen-2024-1YbOCmcjYqnFivIk",
            "Body": "Hello, here is the question about AWS Service",
            "SubmittedBy": "john.doe@unicorn-ltd.io",
            "TimeCreated": "2024-09-15T15:45:22.000Z",
            "AttachmentSet": [],
            "AccountAlias": "Unicorn Ltd - Identity Services"
        },
        {
            "CaseId": "case-081315907440-muen-2024-1YbOCmcjYqnFivIk",
            "Body": "Hello, here is the answer.",
            "SubmittedBy": "Amazon Web Services",
            "TimeCreated": "2024-09-15T15:45:22.000Z",
            "AttachmentSet": [],
            "AccountAlias": "Unicorn Ltd - Identity Services"
        }
    ]
    communications_key = "support-cases/support-cases-communications/payer_id=000001234567/account_id=12345004579/year=2024/month=9/day=15/hour=14/minute=32/case-081315907440-muen-2024-1YbOCmcjYqnFivIk.json"
    data_key = "support-cases/support-cases-data/payer_id=000001234567/account_id=12345004579/year=2024/month=9/day=15/hour=14/minute=32/case-081315907440-muen-2024-1YbOCmcjYqnFivIk.json"
    s3_client.put_object(
        Bucket=COLLECTION_BUCKET,
        Key=data_key,
        Body=json.dumps(case_data),
        ContentType='application/json'
    )
    s3_client.put_object(
        Bucket=COLLECTION_BUCKET,
        Key=communications_key,
        Body='\n'.join([json.dumps(c) for c in case_communications]),
        ContentType='application/json'
    )

    response = boto3.client('events').put_events(
        Entries=[
            {
                'Source': 'supportcases.datacollection.cid.aws',
                'DetailType': 'Event',
                'Detail': json.dumps({
                    'Bucket': COLLECTION_BUCKET,
                    'CommunicationsKey': communications_key,
                    'DataKey': data_key,
                })
            }
        ]
    )
    # Checking if summary is populated
    for i in range(3):
        time.sleep(10)
        case_data_content = json.loads(s3_client.get_object(Bucket=COLLECTION_BUCKET, Key=data_key)['Body'].read().decode('utf-8'))
        if case_data_content['Summary']:
            logger.info(f"Summary = {case_data_content['Summary']}")
            break
    else:
        raise Exception('no Summary produced in 30s')

if __name__ == '__main__':
    pytest.params = {}
    if '--no-teardown' in sys.argv:
        sys.argv.remove('--no-teardown')
        pytest.params['mode'] = 'no-teardown'

    sys.argv = sys.argv[:1]
    pytest.main()
