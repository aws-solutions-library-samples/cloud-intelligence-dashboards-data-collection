"""
Bedrock Logs ETL Job
Reads raw Bedrock invocation log JSON.GZ files from the data lake bucket,
parses them, and writes Parquet files partitioned by account_id/year/month/day
to the processed/ prefix for fast Athena queries.
"""

import sys
import json
import gzip
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType
)

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'SOURCE_BUCKET', 'PROCESSED_PREFIX'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

SOURCE_BUCKET = args['SOURCE_BUCKET']
PROCESSED_PREFIX = args['PROCESSED_PREFIX']
SOURCE_PATH = f's3://{SOURCE_BUCKET}/'
OUTPUT_PATH = f's3://{SOURCE_BUCKET}/{PROCESSED_PREFIX}/'

# Schema matching Bedrock invocation log format
LOG_SCHEMA = StructType([
    StructField('schemaType', StringType(), True),
    StructField('schemaVersion', StringType(), True),
    StructField('timestamp', StringType(), True),
    StructField('accountId', StringType(), True),
    StructField('region', StringType(), True),
    StructField('requestId', StringType(), True),
    StructField('operation', StringType(), True),
    StructField('modelId', StringType(), True),
    StructField('input', StructType([
        StructField('inputBodyJson', StringType(), True),
        StructField('inputContentType', StringType(), True),
        StructField('inputTokenCount', IntegerType(), True),
    ]), True),
    StructField('output', StructType([
        StructField('outputBodyJson', StringType(), True),
        StructField('outputContentType', StringType(), True),
        StructField('outputTokenCount', IntegerType(), True),
    ]), True),
])

# Read all raw JSON.GZ files from AWSLogs paths
raw_path = f'{SOURCE_PATH}*/AWSLogs/*/BedrockModelInvocationLogs/*/*/*/*/*/*.json.gz'

df = spark.read \
    .option('multiLine', False) \
    .schema(LOG_SCHEMA) \
    .json(raw_path)

# Add partition columns derived from timestamp and accountId
df_processed = df \
    .withColumn('account_id', F.col('accountId')) \
    .withColumn('year',  F.date_format(F.to_timestamp(F.col('timestamp')), 'yyyy')) \
    .withColumn('month', F.date_format(F.to_timestamp(F.col('timestamp')), 'MM')) \
    .withColumn('day',   F.date_format(F.to_timestamp(F.col('timestamp')), 'dd')) \
    .withColumnRenamed('schemaType',    'schematype') \
    .withColumnRenamed('schemaVersion', 'schemaversion') \
    .withColumnRenamed('requestId',     'requestid') \
    .withColumnRenamed('operation',     'operation') \
    .withColumnRenamed('modelId',       'modelid') \
    .withColumnRenamed('region',        'region') \
    .drop('accountId')

# Write Parquet partitioned by account_id/year/month/day
df_processed.write \
    .mode('overwrite') \
    .partitionBy('account_id', 'year', 'month', 'day') \
    .parquet(OUTPUT_PATH)

# Register new partitions in Glue catalog — replaces need for crawler
tables = spark.sql("SHOW TABLES IN bedrock_logs").collect()
table_exists = any(row.tableName == "bedrock_invocations_processed" for row in tables)
if table_exists:
    spark.sql("MSCK REPAIR TABLE bedrock_logs.bedrock_invocations_processed")
else:
    print("WARNING: Table bedrock_logs.bedrock_invocations_processed does not exist — skipping MSCK REPAIR")

job.commit()
