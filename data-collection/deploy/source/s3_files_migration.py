"""
Moving s3 objects from old structure to the new one.

Usage:
    When migrating data in the same bucket:

    python3 {prog} <ODC_bucket>

    When migrating data between 2 different buckets:

    python3 {prog} <ODC_source_bucket> <ODC_destination_bucket>

        If source and destination arguments have the same bucket name, the migration will be done in the same bucket.

"""
import re
import sys
import logging
import boto3

logger = logging.getLogger(__name__)

def migrate(bucket):
    s3 = boto3.client('s3')
    payer_id = get_payer()
    mods = {
        # Migration from v0 (no payer_id)
        "ecs-chargeback-data/year=": f"ecs-chargeback/ecs-chargeback-data/payer_id={payer_id}/year=",
        "rds_metrics/rds_stats/year=": f"rds-usage/rds-usage-data/payer_id={payer_id}/year=",
        "budgets/year=": f"budgets/budgets-data/payer_id={payer_id}/year=",
        "rightsizing/year=": f"cost-explorer-rightsizing/cost-explorer-rightsizing-data/payer_id={payer_id}/year=",
        "optics-data-collector/ami-data/year=":      f"inventory/inventory-ami-data/payer_id={payer_id}/year=",
        "optics-data-collector/ebs-data/year=":      f"inventory/inventory-ebs-data/payer_id={payer_id}/year=",
        "optics-data-collector/snapshot-data/year=": f"inventory/inventory-snapshot-data/payer_id={payer_id}/year=",
        "optics-data-collector/ta-data/year=":       f"trusted-advisor/trusted-advisor-data/payer_id={payer_id}/year=",
        "Compute_Optimizer/Compute_Optimizer_ec2_instance/year=":   f"compute_optimizer/compute_optimizer_ec2_instance/payer_id={payer_id}/year=",
        "Compute_Optimizer/Compute_Optimizer_auto_scale/year=":     f"compute_optimizer/compute_optimizer_auto_scale/payer_id={payer_id}/year=",
        "Compute_Optimizer/Compute_Optimizer_lambda/year=":         f"compute_optimizer/compute_optimizer_lambda/payer_id={payer_id}/year=",
        "Compute_Optimizer/Compute_Optimizer_ebs_volume/year=":     f"compute_optimizer/compute_optimizer_ebs_volume/payer_id={payer_id}/year=",
        "reserveinstance/year=":    f"reserveinstance/payer_id={payer_id}/year=",
        "savingsplan/year=":        f"savingsplan/payer_id={payer_id}/year=",
        "transitgateway/year=":     f"transit-gateway/transit-gateway-data/payer_id={payer_id}/year=",

        # Migration from v1 (payer_id exists)
        "ecs-chargeback-data/payer_id=": "ecs-chargeback/ecs-chargeback-data/payer_id=",
        "rds_metrics/rds_stats/payer_id=": "rds-usage/rds-usage-data/payer_id=",
        "budgets/payer_id=": "budgets/budgets-data/payer_id=",
        "rightsizing/payer_id=": "cost-explorer-rightsizing/cost-explorer-rightsizing-data/payer_id=",
        "optics-data-collector/ami-data/payer_id=":      "inventory/inventory-ami-data/payer_id=",
        "optics-data-collector/ebs-data/payer_id=":      "inventory/inventory-ebs-data/payer_id=",
        "optics-data-collector/snapshot-data/payer_id=": "inventory/inventory-snapshot-data/payer_id",
        "optics-data-collector/ta-data/payer_id=":       "trusted-advisor/trusted-advisor-data/payer_id=",
        "Compute_Optimizer/Compute_Optimizer_ec2_instance/payer_id=": "compute_optimizer/compute_optimizer_ec2_instance/payer_id=",
        "Compute_Optimizer/Compute_Optimizer_auto_scale/payer_id=":   "compute_optimizer/compute_optimizer_auto_scale/payer_id=",
        "Compute_Optimizer/Compute_Optimizer_lambda/payer_id=":       "compute_optimizer/compute_optimizer_lambda/payer_id=",
        "Compute_Optimizer/Compute_Optimizer_ebs_volume/payer_id=":   "compute_optimizer/compute_optimizer_ebs_volume/payer_id=",
        "reserveinstance/payer_id=": "reserveinstance/payer_id=",
        "savingsplan/payer_id=": "savingsplan/payer_id=",
        "transitgateway/payer_id=": "transit-gateway/transit-gateway-data/payer_id=",

        # Migration from v1.1 (adding payer to organizations)
        "organization/organization-data/([a-z\-]*?)-(\d{12}).json": rf"organization/organization-data/payer_id=\2/\1.json",

        # Migration from v2.0 to v3.0 (read roles as stack set and step functions implementation)
        "organization/organization-data/payer_id=": "organizations/organization-data/payer_id=",
        "cost-explorer-cost-anomaly/cost-anomaly-data/payer_id=": "cost-anomaly/cost-anomaly-data/payer_id=",
        "rds_usage_data/rds-usage-data/payer_id=": "rds-usage/rds-usage-data/payer_id=",
    }

    for old_prefix, new_prefix in mods.items():
        logger.debug(f'Searching for {old_prefix} in {bucket}' )
        contents =s3.list_objects_v2(Bucket=bucket, Prefix=old_prefix).get('Contents', [])
        for content in contents:
            try:
                key = content["Key"]
                new_key = re.sub(old_prefix, new_prefix, key)
                logger.info(f'  Moving {key} to {new_key}')
                copy_source = {'Bucket': bucket, 'Key': key}
                s3.copy_object(Bucket=bucket, CopySource=copy_source, Key=new_key)
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception as e:
                logger.warning(e)

def migrate_v2(source_bucket, dest_bucket):
    s3 = boto3.client("s3")
    payer_id = get_payer()
    available_mods = {
        "budgets": {
            # Migration from v0 (no payer_id)
            "budgets/year=": f"budgets/budgets-data/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "budgets/payer_id=": "budgets/budgets-data/payer_id=",
        },
        "optics-data-collector": {
            # Migration from v0 (no payer_id)
            "optics-data-collector/ami-data/year=": f"inventory/inventory-ami-data/payer_id={payer_id}/year=",
            "optics-data-collector/ebs-data/year=": f"inventory/inventory-ebs-data/payer_id={payer_id}/year=",
            "optics-data-collector/snapshot-data/year=": f"inventory/inventory-snapshot-data/payer_id={payer_id}/year=",
            "optics-data-collector/ta-data/year=": f"trusted-advisor/trusted-advisor-data/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "optics-data-collector/ami-data/payer_id=": "inventory/inventory-ami-data/payer_id=",
            "optics-data-collector/ebs-data/payer_id=": "inventory/inventory-ebs-data/payer_id=",
            "optics-data-collector/snapshot-data/payer_id=": "inventory/inventory-snapshot-data/payer_id",
            "optics-data-collector/ta-data/payer_id=": "trusted-advisor/trusted-advisor-data/payer_id=",
        },
        "ecs-chargeback-data": {
            # Migration from v0 (no payer_id)
            "ecs-chargeback-data/year=": f"ecs-chargeback/ecs-chargeback-data/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "ecs-chargeback-data/payer_id=": "ecs-chargeback/ecs-chargeback-data/payer_id=",
        },
        "rds_metrics": {
            # Migration from v0 (no payer_id)
            "rds_metrics/rds_stats/year=": f"rds-usage/rds-usage-data/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "rds_metrics/rds_stats/payer_id=": "rds-usage/rds-usage-data/payer_id=",
        },
        "rightsizing": {
            # Migration from v0 (no payer_id)
            "rightsizing/year=": f"cost-explorer-rightsizing/cost-explorer-rightsizing-data/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "rightsizing/payer_id=": "cost-explorer-rightsizing/cost-explorer-rightsizing-data/payer_id=",
        },
        "Compute_Optimizer": {
            # Migration from v0 (no payer_id)
            "Compute_Optimizer/Compute_Optimizer_ec2_instance/year=": f"compute_optimizer/compute_optimizer_ec2_instance/payer_id={payer_id}/year=",
            "Compute_Optimizer/Compute_Optimizer_auto_scale/year=": f"compute_optimizer/compute_optimizer_auto_scale/payer_id={payer_id}/year=",
            "Compute_Optimizer/Compute_Optimizer_lambda/year=": f"compute_optimizer/compute_optimizer_lambda/payer_id={payer_id}/year=",
            "Compute_Optimizer/Compute_Optimizer_ebs_volume/year=": f"compute_optimizer/compute_optimizer_ebs_volume/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "Compute_Optimizer/Compute_Optimizer_ec2_instance/payer_id=": "compute_optimizer/compute_optimizer_ec2_instance/payer_id=",
            "Compute_Optimizer/Compute_Optimizer_auto_scale/payer_id=": "compute_optimizer/compute_optimizer_auto_scale/payer_id=",
            "Compute_Optimizer/Compute_Optimizer_lambda/payer_id=": "compute_optimizer/compute_optimizer_lambda/payer_id=",
            "Compute_Optimizer/Compute_Optimizer_ebs_volume/payer_id=": "compute_optimizer/compute_optimizer_ebs_volume/payer_id=",
        },
        "reserveinstance": {
            # Migration from v0 (no payer_id)
            "reserveinstance/year=": f"reserveinstance/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "reserveinstance/payer_id=": "reserveinstance/payer_id=",
        },
        "savingsplan": {
            # Migration from v0 (no payer_id)
            "savingsplan/year=": f"savingsplan/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "savingsplan/payer_id=": "savingsplan/payer_id=",
        },
        "transitgateway": {
            # Migration from v0 (no payer_id)
            "transitgateway/year=": f"transit-gateway/transit-gateway-data/payer_id={payer_id}/year=",
            # Migration from v1 (payer_id exists)
            "transitgateway/payer_id=": "transit-gateway/transit-gateway-data/payer_id=",
        },
        "organization": {
            # Migration from v1.1 (adding payer to organizations)
            "organization/organization-data/([a-z\-]*?)-(\d{12}).json": rf"organization/organization-data/payer_id=\2/\1.json",
            # Migration from v2.0 to v3.0 (read roles as stack set and step functions implementation)
            "organization/organization-data/payer_id=": "organizations/organization-data/payer_id=",
        },
        "cost-explorer-cost-anomaly": {
            # Migration from v2.0 to v3.0 (read roles as stack set and step functions implementation)
            "cost-explorer-cost-anomaly/cost-anomaly-data/payer_id=": "cost-anomaly/cost-anomaly-data/payer_id=",
        },
        "rds_usage_data": {
            # Migration from v2.0 to v3.0 (read roles as stack set and step functions implementation)
            "rds_usage_data/rds-usage-data/payer_id=": "rds-usage/rds-usage-data/payer_id=",
        },
    }

    # Apply valid mods and copy objects
    more_objects_to_fetch = True
    next_continuation_token = None

    list_objects_result = s3.list_objects_v2(
        Bucket=source_bucket,
    )

    while more_objects_to_fetch:
        contents = list_objects_result.get("Contents", [])
        for content in contents:
            try:
                source_key = content["Key"]
                applicable_mods = get_applicable_mods(source_key, available_mods)
                new_key = source_key
                for old_prefix, new_prefix in applicable_mods.items():
                    new_key = re.sub(
                        old_prefix, new_prefix, source_key
                    )  # Returns the same source_key string when no match exists for the given pattern
                    if new_key != source_key:
                        logger.info(f"Modifying source {source_key} to {new_key}")
                copy_source = {"Bucket": source_bucket, "Key": source_key}
                s3.copy_object(Bucket=dest_bucket, CopySource=copy_source, Key=new_key)
                logger.info(
                    f"Moving object source s3://{source_bucket}/{source_key} to s3://{dest_bucket}/{new_key}"
                )
                # s3.delete_object(Bucket=source_bucket, Key=source_key) # Uncomment this line if you want to delete data from the source bucket as the objects are copied
            except Exception as e:
                logger.warning(e)

        more_objects_to_fetch = list_objects_result["IsTruncated"]
        if more_objects_to_fetch:
            next_continuation_token = list_objects_result["NextContinuationToken"]
            list_objects_result = s3.list_objects_v2(
                Bucket=source_bucket,
                ContinuationToken=next_continuation_token,
            )
        else:
            next_continuation_token = None

def get_applicable_mods(object_key: str, available_mods: dict):
    top_prefix = object_key.split("/")[0]
    return available_mods.get(top_prefix, {})

def get_payer():
    org = boto3.client('organizations')
    try:
        payer_id = org.describe_organization()["Organization"]['MasterAccountId']
        logger.info(f'payer_id={payer_id}')
    except org.exceptions.AccessDeniedException:
        logger.info('Cannot read organizations. Please enter payer_id (12 digits)')
        payer_id = input('payer_id>')
        assert re.match(r'^\d{12}$', payer_id), 'Wrong user input. Payer id must be 12 digits'
    except org.exceptions.AWSOrganizationsNotInUseException:
        sts = boto3.client('sts')
        payer_id = sts.get_caller_identity()['Account']
        logger.info(f'Account is not a part of org. Using Account id = {payer_id}')
    return payer_id


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(logging.DEBUG)
    try:
        source_bucket = sys.argv[1]
        try:
            dest_bucket = sys.argv[2]
        except IndexError as exc:
            dest_bucket = source_bucket
    except:
        print(__doc__.format(prog=sys.argv[0]))
        exit(1)

    if source_bucket == dest_bucket:
        logger.info(f"Migrating files in source={source_bucket}")
        migrate(source_bucket)
    else:
        logger.info(
            f"Migrating from source={source_bucket} to destination={dest_bucket}"
        )
        migrate_v2(source_bucket, dest_bucket)

