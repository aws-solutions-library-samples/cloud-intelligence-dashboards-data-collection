import boto3
import os
import logging
import time

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    Lambda function to create Athena views for RDS Performance Insights data
    """
    logger.info("Starting Athena views creation")
    
    # Get environment variables
    glue_database_name = os.environ.get('GLUE_DATABASE_NAME')
    cur_database_name = os.environ.get('CUR_DATABASE_NAME')
    cur_table_name = os.environ.get('CUR_TABLE_NAME')
    
    if not glue_database_name or not cur_database_name or not cur_table_name:
        raise ValueError("GLUE_DATABASE_NAME, CUR_DATABASE_NAME, and CUR_TABLE_NAME environment variables are required")
    
    # Create Athena client
    athena_client = boto3.client('athena')
    
    # Create workgroup if it doesn't exist
    workgroup_name = "RdsMultitenantWorkgroup"
    try:
        create_workgroup_if_not_exists(athena_client, workgroup_name)
    except Exception as e:
        logger.error(f"Error creating workgroup: {str(e)}")
        raise
    
    # Create views
    try:
        # Create view for RDS Performance Insights data
        create_pi_view(athena_client, workgroup_name, glue_database_name)
        
        # Create view for joining Performance Insights data with CUR data
        create_pi_cur_view(athena_client, workgroup_name, glue_database_name, cur_database_name, cur_table_name)
        
        # Create view for tenant cost allocation
        create_tenant_cost_view(athena_client, workgroup_name, glue_database_name)
        
    except Exception as e:
        logger.error(f"Error creating views: {str(e)}")
        raise
    
    return {
        'statusCode': 200,
        'body': 'Athena views created successfully'
    }

def create_workgroup_if_not_exists(athena_client, workgroup_name):
    """Create Athena workgroup if it doesn't exist"""
    try:
        athena_client.get_work_group(WorkGroup=workgroup_name)
        logger.info(f"Workgroup {workgroup_name} already exists")
    except athena_client.exceptions.InvalidRequestException:
        logger.info(f"Creating workgroup {workgroup_name}")
        athena_client.create_work_group(
            Name=workgroup_name,
            Configuration={
                'ResultConfiguration': {
                    'EncryptionConfiguration': {
                        'EncryptionOption': 'SSE_S3'
                    }
                },
                'EnforceWorkGroupConfiguration': True,
                'PublishCloudWatchMetricsEnabled': True,
                'BytesScannedCutoffPerQuery': 10000000000,
                'RequesterPaysEnabled': False
            },
            Description='Workgroup for RDS Multitenant Performance Insights views'
        )

def execute_query(athena_client, workgroup_name, database, query):
    """Execute Athena query and wait for completion"""
    response = athena_client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': database
        },
        WorkGroup=workgroup_name
    )
    
    query_execution_id = response['QueryExecutionId']
    
    # Wait for query to complete
    state = 'RUNNING'
    max_retries = 10
    retry_count = 0
    
    while state == 'RUNNING' and retry_count < max_retries:
        response = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
        state = response['QueryExecution']['Status']['State']
        
        if state == 'RUNNING':
            retry_count += 1
            time.sleep(3)
    
    if state == 'SUCCEEDED':
        logger.info(f"Query executed successfully: {query_execution_id}")
    else:
        error_message = response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
        logger.error(f"Query failed: {error_message}")
        raise Exception(f"Query failed: {error_message}")
    
    return query_execution_id

def create_pi_view(athena_client, workgroup_name, database):
    """Create view for RDS Performance Insights data"""
    logger.info("Creating RDS Performance Insights view")
    
    query = f"""
    CREATE OR REPLACE VIEW {database}.rds_pi_consolidated AS
    SELECT
        account_id,
        resourcearn,
        instance_id,
        num_vcpus,
        `db.user.name` as db_user_name,
        timestamp,
        metric,
        value
    FROM
        {database}.rds_pi_data_hourly
    """
    
    execute_query(athena_client, workgroup_name, database, query)

def create_pi_cur_view(athena_client, workgroup_name, pi_database, cur_database, cur_table):
    """Create view joining Performance Insights data with CUR data"""
    logger.info("Creating RDS Performance Insights with CUR view")
    
    query = f"""
    CREATE OR REPLACE VIEW {pi_database}.rds_pi_with_cur AS
    WITH pi_data AS (
        SELECT
            account_id,
            resourcearn,
            instance_id,
            num_vcpus,
            db_user_name,
            timestamp,
            metric,
            value,
            SUBSTR(resourcearn, STRPOS(resourcearn, ':db:') + 4) AS db_identifier
        FROM
            {pi_database}.rds_pi_consolidated
    ),
    cur_data AS (
        SELECT
            line_item_usage_account_id as account_id,
            line_item_resource_id,
            line_item_usage_type,
            product_database_engine,
            line_item_usage_start_date,
            line_item_usage_end_date,
            line_item_unblended_cost,
            CASE
                WHEN line_item_resource_id LIKE 'arn:aws:rds:%' THEN SUBSTR(line_item_resource_id, STRPOS(line_item_resource_id, ':db:') + 4)
                ELSE NULL
            END AS db_identifier
        FROM
            {cur_database}.{cur_table}
        WHERE
            product_servicecode = 'AmazonRDS'
            AND line_item_line_item_type = 'Usage'
    )
    SELECT
        pi.account_id,
        pi.resourcearn,
        pi.instance_id,
        pi.num_vcpus,
        pi.db_user_name,
        pi.timestamp,
        pi.metric,
        pi.value,
        cur.line_item_usage_type,
        cur.product_database_engine,
        cur.line_item_usage_start_date,
        cur.line_item_usage_end_date,
        cur.line_item_unblended_cost
    FROM
        pi_data pi
    JOIN
        cur_data cur
    ON
        pi.db_identifier = cur.db_identifier
        AND pi.account_id = cur.account_id
        AND pi.timestamp BETWEEN cur.line_item_usage_start_date AND cur.line_item_usage_end_date
    """
    
    execute_query(athena_client, workgroup_name, pi_database, query)

def create_tenant_cost_view(athena_client, workgroup_name, database):
    """Create view for tenant cost allocation"""
    logger.info("Creating tenant cost allocation view")
    
    query = f"""
    CREATE OR REPLACE VIEW {database}.rds_tenant_cost_allocation AS
    WITH tenant_usage AS (
        SELECT
            account_id,
            instance_id,
            db_user_name as tenant_id,
            DATE(timestamp) as usage_date,
            SUM(value) as total_db_load,
            COUNT(*) as sample_count
        FROM
            {database}.rds_pi_consolidated
        WHERE
            metric = 'db.load.avg'
        GROUP BY
            account_id, instance_id, db_user_name, DATE(timestamp)
    ),
    instance_usage AS (
        SELECT
            account_id,
            instance_id,
            usage_date,
            SUM(total_db_load) as instance_total_load,
            MAX(sample_count) as sample_count
        FROM
            tenant_usage
        GROUP BY
            account_id, instance_id, usage_date
    ),
    instance_costs AS (
        SELECT
            account_id,
            instance_id,
            DATE(line_item_usage_start_date) as usage_date,
            SUM(line_item_unblended_cost) as daily_cost
        FROM
            {database}.rds_pi_with_cur
        GROUP BY
            account_id, instance_id, DATE(line_item_usage_start_date)
    )
    SELECT
        tu.account_id,
        tu.instance_id,
        tu.tenant_id,
        tu.usage_date,
        tu.total_db_load,
        iu.instance_total_load,
        CASE
            WHEN iu.instance_total_load > 0 THEN tu.total_db_load / iu.instance_total_load
            ELSE 0
        END as usage_percentage,
        ic.daily_cost,
        CASE
            WHEN iu.instance_total_load > 0 THEN (tu.total_db_load / iu.instance_total_load) * ic.daily_cost
            ELSE 0
        END as allocated_cost
    FROM
        tenant_usage tu
    JOIN
        instance_usage iu ON tu.account_id = iu.account_id AND tu.instance_id = iu.instance_id AND tu.usage_date = iu.usage_date
    LEFT JOIN
        instance_costs ic ON tu.account_id = ic.account_id AND tu.instance_id = ic.instance_id AND tu.usage_date = ic.usage_date
    ORDER BY
        tu.usage_date, tu.instance_id, allocated_cost DESC
    """
    
    execute_query(athena_client, workgroup_name, database, query)