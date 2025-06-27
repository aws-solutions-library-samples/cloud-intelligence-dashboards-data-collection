import boto3
import json

def lambda_handler(event, context):
    rds_client = boto3.client('rds')
    
    paginator = rds_client.get_paginator('describe_db_major_engine_versions')
    
    for page in paginator.paginate():
        for engine_version in page['DBMajorEngineVersions']:
            print(json.dumps(engine_version, indent=2, default=str))
    
    return {'statusCode': 200}