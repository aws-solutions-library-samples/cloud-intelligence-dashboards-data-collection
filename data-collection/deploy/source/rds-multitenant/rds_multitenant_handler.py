import boto3
import json
import os
import datetime
import logging
import pandas as pd
import io
import pyarrow as pa
import pyarrow.parquet as pq

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    Lambda function to collect RDS Performance Insights metrics and store them in S3
    """
    logger.info("Starting RDS Performance Insights data collection")
    
    # Get environment variables
    metrics_bucket = os.environ.get('METRICS_BUCKET')
    metrics_period = int(os.environ.get('METRICS_PERIOD_IN_SECONDS', '3600'))
    metrics_s3_prefix = os.environ.get('METRICS_S3_PREFIX', 'rds_pi_data')
    
    if not metrics_bucket:
        raise ValueError("METRICS_BUCKET environment variable is required")
    
    # Get current timestamp
    now = datetime.datetime.utcnow()
    end_time = now
    start_time = end_time - datetime.timedelta(seconds=metrics_period)
    
    # Get list of regions
    ec2_client = boto3.client('ec2')
    regions = [region['RegionName'] for region in ec2_client.describe_regions()['Regions']]
    
    # Process each region
    for region in regions:
        try:
            process_region(region, metrics_bucket, metrics_s3_prefix, start_time, end_time, metrics_period)
        except Exception as e:
            logger.error(f"Error processing region {region}: {str(e)}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('RDS Performance Insights data collection completed')
    }

def process_region(region, metrics_bucket, metrics_s3_prefix, start_time, end_time, metrics_period):
    """Process a single AWS region"""
    logger.info(f"Processing region: {region}")
    
    # Create RDS client for the region
    rds_client = boto3.client('rds', region_name=region)
    
    # Get list of DB instances in the region
    try:
        response = rds_client.describe_db_instances()
        db_instances = response['DBInstances']
        
        # Process each DB instance
        for db_instance in db_instances:
            try:
                process_db_instance(db_instance, region, metrics_bucket, metrics_s3_prefix, start_time, end_time, metrics_period)
            except Exception as e:
                logger.error(f"Error processing DB instance {db_instance['DBInstanceIdentifier']}: {str(e)}")
                
        # Handle pagination
        while 'Marker' in response:
            response = rds_client.describe_db_instances(Marker=response['Marker'])
            db_instances = response['DBInstances']
            
            for db_instance in db_instances:
                try:
                    process_db_instance(db_instance, region, metrics_bucket, metrics_s3_prefix, start_time, end_time, metrics_period)
                except Exception as e:
                    logger.error(f"Error processing DB instance {db_instance['DBInstanceIdentifier']}: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error listing DB instances in region {region}: {str(e)}")

def process_db_instance(db_instance, region, metrics_bucket, metrics_s3_prefix, start_time, end_time, metrics_period):
    """Process a single DB instance"""
    db_instance_id = db_instance['DBInstanceIdentifier']
    logger.info(f"Processing DB instance: {db_instance_id}")
    
    # Check if Performance Insights is enabled
    if not db_instance.get('PerformanceInsightsEnabled', False):
        logger.info(f"Performance Insights not enabled for {db_instance_id}, skipping")
        return
    
    # Get Performance Insights metrics
    pi_client = boto3.client('pi', region_name=region)
    resource_arn = db_instance['PerformanceInsightsEnabled'] and db_instance['PerformanceInsightsARN']
    
    if not resource_arn:
        logger.info(f"Performance Insights ARN not available for {db_instance_id}, skipping")
        return
    
    # Get DB CPU utilization by user
    try:
        metrics_response = pi_client.get_resource_metrics(
            ServiceType='RDS',
            Identifier=resource_arn,
            MetricQueries=[
                {
                    'Metric': 'db.load.avg',
                    'GroupBy': {
                        'Group': 'db.user',
                        'Dimensions': ['db.user.name']
                    }
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
            PeriodInSeconds=metrics_period
        )
        
        # Process and store metrics
        process_metrics(metrics_response, db_instance, resource_arn, metrics_bucket, metrics_s3_prefix)
        
    except Exception as e:
        logger.error(f"Error getting Performance Insights metrics for {db_instance_id}: {str(e)}")

def process_metrics(metrics_response, db_instance, resource_arn, metrics_bucket, metrics_s3_prefix):
    """Process and store Performance Insights metrics"""
    db_instance_id = db_instance['DBInstanceIdentifier']
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    num_vcpus = db_instance.get('DBInstanceClass', '').split('.')[1][0] if 'DBInstanceClass' in db_instance else 0
    
    # Extract metrics data
    metrics_data = []
    
    for metric_result in metrics_response.get('MetricList', []):
        metric_name = metric_result.get('Metric')
        
        for datapoint in metric_result.get('DataPoints', []):
            timestamp = datapoint.get('Timestamp')
            
            # Format timestamp for partitioning
            year = timestamp.strftime('%Y')
            month = timestamp.strftime('%m')
            day = timestamp.strftime('%d')
            hour = timestamp.strftime('%H')
            
            # Process each group
            for group in datapoint.get('Group', []):
                dimensions = {}
                for dimension in group.get('Dimensions', []):
                    for key, value in dimension.items():
                        dimensions[key] = value
                
                user_name = dimensions.get('db.user.name', 'unknown')
                value = group.get('Value', 0)
                
                # Add to metrics data
                metrics_data.append({
                    'metric': metric_name,
                    'resourcearn': resource_arn,
                    'instance_id': db_instance_id,
                    'num_vcpus': float(num_vcpus),
                    'db.user.name': user_name,
                    'timestamp': timestamp.isoformat(),
                    'value': float(value),
                    'account_id': account_id,
                    'year': year,
                    'month': month,
                    'day': day,
                    'hour': hour
                })
    
    if not metrics_data:
        logger.info(f"No metrics data found for {db_instance_id}")
        return
    
    # Convert to DataFrame and save as Parquet
    df = pd.DataFrame(metrics_data)
    
    # Create S3 key with partitioning
    s3_key = f"{metrics_s3_prefix}/account_id={account_id}/year={year}/month={month}/day={day}/hour={hour}/{db_instance_id}_{timestamp.strftime('%Y%m%d%H%M%S')}.parquet"
    
    # Convert to Parquet and upload to S3
    table = pa.Table.from_pandas(df)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    
    s3_client = boto3.client('s3')
    s3_client.put_object(
        Bucket=metrics_bucket,
        Key=s3_key,
        Body=buf.getvalue()
    )
    
    logger.info(f"Uploaded metrics data for {db_instance_id} to s3://{metrics_bucket}/{s3_key}")