# RDS Multi-Tenant Cost Visibility Module

## Overview

This module helps improve cost visibility for Amazon RDS multi-tenant instances by leveraging Performance Insights and Amazon Athena. It enables organizations to accurately allocate costs to different tenants and optimize database performance.

## Features

- Collects Amazon RDS Performance Insights data for multi-tenant databases
- Creates Athena views to analyze tenant-specific resource usage
- Integrates with Cost and Usage Report (CUR 2.0) data for cost allocation
- Provides visibility into database resource consumption by tenant

## Prerequisites

- [CUR 2.0](https://docs.aws.amazon.com/cur/latest/userguide/data-exports-migrate-two.html) enabled and mapped to a Glue table
- Amazon RDS instances with Performance Insights enabled
- Proper IAM permissions to access RDS Performance Insights API

## How It Works

1. A Lambda function collects Performance Insights metrics from all RDS instances across regions
2. The metrics are stored in an S3 bucket with proper partitioning
3. Glue crawlers create and maintain tables in the Glue Data Catalog
4. Athena views are created to join Performance Insights data with CUR data
5. The final view provides tenant-specific cost allocation based on database usage

## Athena Views

The module creates the following Athena views:

1. **rds_pi_consolidated**: Consolidates Performance Insights data
2. **rds_pi_with_cur**: Joins Performance Insights data with CUR data
3. **rds_tenant_cost_allocation**: Provides tenant-specific cost allocation

## Usage

After deployment, you can use the Athena views to:
- Analyze database resource usage by tenant
- Allocate costs based on actual resource consumption
- Identify optimization opportunities for multi-tenant databases

## Example Queries

### Get tenant usage by database instance
```sql
SELECT
    instance_id,
    tenant_id,
    usage_date,
    SUM(total_db_load) as total_load,
    SUM(allocated_cost) as total_cost
FROM
    rds_performance_insights_db.rds_tenant_cost_allocation
WHERE
    usage_date BETWEEN DATE '2023-01-01' AND DATE '2023-01-31'
GROUP BY
    instance_id, tenant_id, usage_date
ORDER BY
    instance_id, total_cost DESC;
```

### Get daily cost allocation for a specific tenant
```sql
SELECT
    usage_date,
    SUM(allocated_cost) as daily_cost
FROM
    rds_performance_insights_db.rds_tenant_cost_allocation
WHERE
    tenant_id = 'app_user'
    AND usage_date BETWEEN DATE '2023-01-01' AND DATE '2023-01-31'
GROUP BY
    usage_date
ORDER BY
    usage_date;
```

## Based On

This module is based on the AWS Database Blog post: [Improve cost visibility of an Amazon RDS multi-tenant instance with Performance Insights and Amazon Athena](https://aws.amazon.com/blogs/database/improve-cost-visibility-of-an-amazon-rds-multi-tenant-instance-with-performance-insights-and-amazon-athena/)