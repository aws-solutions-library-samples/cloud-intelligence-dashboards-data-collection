---
inclusion: always
---

# Module Creation System

This directory contains comprehensive guidance for creating new data collection modules in the Cloud Intelligence Dashboards project.

## Available Resources

### 1. Module Creation Guide (`module-creation-guide.md`)
**When to use**: Reference this when creating any new module

Comprehensive documentation covering:
- Complete module structure and all required components
- Standard parameters, conditions, and outputs
- IAM role patterns and security best practices
- Lambda function structure and Python code patterns
- Glue crawler configuration
- Step Function and Scheduler setup
- Naming conventions and best practices
- Testing checklist

### 2. Module Template (`module-template.yaml`)
**When to use**: Copy this as a starting point for new modules

A complete, ready-to-customize CloudFormation template with:
- All standard parameters and resources
- TODO markers for customization points
- Placeholder Python code structure
- Comments explaining what needs to be replaced
- All required AWS resources pre-configured

### 3. Quick Reference (`module-quick-reference.md`)
**When to use**: Quick lookup while implementing modules

Fast reference for:
- Common AWS service patterns
- IAM policy examples
- Data storage patterns
- Environment variable configuration
- Schedule expressions
- Troubleshooting common issues
- Testing commands

## How to Create a New Module

### Option 1: Using the Hook (Recommended)

1. Open the Agent Hooks panel in Kiro
2. Find "Create New Data Collection Module" hook
3. Trigger the hook
4. Answer the prompts about your module
5. The agent will generate a complete module file for you

### Option 2: Manual Creation

1. **Decide module type**: Determine if your module targets management accounts only or linked accounts
2. Copy `.kiro/steering/module-template.yaml` to `data-collection/deploy/module-<your-service>.yaml`
3. **Choose role parameter**: Delete either ManagementRoleName or MultiAccountRoleName based on your module type
4. Search for all `TODO` markers in the file
5. Replace placeholders with your service-specific values:
   - `[MODULE-NAME]` → your module name (kebab-case)
   - `[SERVICE_NAME]` → AWS service name
   - `[SERVICE_DESCRIPTION]` → what data you're collecting
   - `'service-name'` → actual boto3 service name
   - `'data-type'` → your data prefix
6. Update IAM policies and environment variables to use your chosen role parameter
7. Implement the data collection logic in the Lambda function
8. Add any additional IAM permissions needed
9. Delete GlueRoleARN parameter if not using Glue crawlers (recommended)
10. Test the deployment

## Module Structure at a Glance

```
module-<name>.yaml
├── Parameters (20+ standard + custom)
├── Conditions (KMS encryption)
├── Outputs (Step Function ARN)
└── Resources
    ├── LambdaRole (IAM permissions)
    ├── LambdaFunction (data collection logic)
    ├── LogGroup (CloudWatch logs)
    ├── DataTable(s) (Manual Athena table definitions with partition projection)
    ├── ModuleStepFunction (orchestration - NO crawlers)
    ├── ModuleRefreshSchedule (EventBridge)
    └── AnalyticsExecutor (registration)
```

**Important**: This project does NOT use Glue crawlers. All Athena tables are defined manually with partition projection for better performance and automation.

## Key Concepts

### Module Types and Role Selection

**CRITICAL**: Every module must use EITHER ManagementRoleName OR MultiAccountRoleName parameter, never both.

#### Management Account Modules
- Use `ManagementRoleName` parameter
- Collect organization-wide data from management/payer account only
- Use `CollectionType: "Payers"` in Step Function
- Examples: Organizations, Consolidated Billing

#### Linked Account Modules
- Use `MultiAccountRoleName` parameter
- Collect account-specific resources from all linked accounts
- Use `CollectionType: "LINKED"` in Step Function
- Examples: EC2 Inventory, RDS Usage, License Manager

### Collection Types
- **Payers**: Collect from management/payer accounts only (organization-wide data)
- **LINKED**: Collect from all linked accounts (account-specific resources)

### Data Partitioning
All data is stored in S3 with this structure:
```
s3://bucket/module-name/module-name-data-type/
  year=2024/
    month=02/
      day=16/
        123456789012_987654321098_20240216.json
        123456789012_111222333444_20240216.json
```

**File Naming**: `payer_id_account_id_yyyymmdd.json`
- Example: `123456789012_987654321098_20240216.json`

**Partitioning**: Date-based only (year/month/day)
- Payer ID and account ID are stored as columns in the data, not as partitions
- Enables efficient date-range queries without account-level partition overhead

### Lambda Function Flow
1. Receive event with account ID (and optionally payer ID) from Step Function
2. Assume cross-account role
3. Create AWS service client with assumed credentials
4. Collect data with pagination
5. Add payer_id and account_id fields to each record
6. Store data to S3 with date-based partitioning and proper file naming
7. Return success

### Step Function Orchestration
1. AccountCollector Lambda lists accounts
2. Map state processes each account in parallel
3. Module Lambda collects data for each account
4. Data is immediately queryable via Athena (partition projection)
5. Analytics executor registers completion

**Note**: No Glue crawlers are used. Tables are defined manually with partition projection for instant data availability.

## Common Customization Points

### 1. Multiple Data Types
If collecting different types of data:
- Add parameters for each data prefix
- Create separate Athena table for each type (with partition projection)
- Store each type with different prefix
- Step Function Crawlers parameter should be empty array: `'[]'`

### 2. Service-Specific Regions
Some services require specific regions:
```python
region_name="us-east-1"  # For License Manager, Organizations, etc.
```

### 3. Organization vs Account APIs
Some services have both:
```python
USE_ORG = 'local' != os.environ.get('API', 'org')
if USE_ORG:
    response = client.list_for_organization()
else:
    response = client.list_resources()
```

### 4. Rate Limiting
Add EXTRA_PAUSE support for throttling:
```python
EXTRA_PAUSE = float(os.environ.get('EXTRA_PAUSE', '0'))
if EXTRA_PAUSE > 0:
    time.sleep(EXTRA_PAUSE)
```

### 5. Table Schema Definition
Always define explicit schemas matching your data structure:
```yaml
Columns:
  - Name: resource_id
    Type: string
  - Name: resource_name
    Type: string
  - Name: created_timestamp
    Type: bigint
  - Name: tags
    Type: array<struct<key:string,value:string>>
```

## Integration with Main Deployment

After creating a module, you may need to:
1. Add it to `deploy-data-collection.yaml` as an optional module
2. Update documentation in `data-collection/README.md`
3. Add integration tests in `test/`
4. Update `CHANGELOG.md`

## Examples to Reference

Good examples of different patterns:
- **Simple single-type**: `module-budgets.yaml`
- **Multiple data types**: `module-license-manager.yaml`
- **Complex with sub-state machine**: `module-health-events.yaml`
- **Organization-wide**: `module-organization.yaml`
- **Account-specific**: `module-inventory.yaml`

**Note**: Some existing modules may still use Glue crawlers. New modules should use manual table definitions with partition projection instead.

## Getting Help

When creating a module, you can:
1. Reference the steering documents in this directory
2. Look at existing modules for patterns
3. Use the "Create New Data Collection Module" hook
4. Ask Kiro to help with specific implementation details

## File References

Use these references in your prompts to Kiro:
- `#[[file:module-creation-guide.md]]` - Full guide
- `#[[file:module-template.yaml]]` - Template file
- `#[[file:module-quick-reference.md]]` - Quick lookup
