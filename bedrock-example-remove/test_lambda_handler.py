"""
Local test for the CFN custom resource Lambda handler.
Simulates a Create event without actually calling S3 or the CFN response URL.
"""
import json
from urllib.request import urlopen, Request

# ---- paste the handler code inline for testing ----

def send_response(event, context, status, data={}):
    body = json.dumps({
        'Status': status,
        'Reason': data.get('Error', 'See CloudWatch'),
        'PhysicalResourceId': event.get('PhysicalResourceId', 'test-stream'),
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': data,
    }).encode()
    print(f"send_response called: status={status}, body={body.decode()}")

SCRIPT = r"""
import sys
print("hello from glue script")
"""

def handler(event, context=None):
    props = event.get('ResourceProperties', {})
    bucket = props['Bucket']
    key = props['Key']
    try:
        print(f"Would upload script to s3://{bucket}/{key}")
        print(f"Script length: {len(SCRIPT.strip())} chars")
        send_response(event, context or {}, 'SUCCESS')
    except Exception as e:
        send_response(event, context or {}, 'FAILED', {'Error': str(e)})

# ---- test ----
if __name__ == '__main__':
    test_event = {
        'RequestType': 'Create',
        'ResponseURL': 'https://example.com/response',
        'StackId': 'arn:aws:cloudformation:us-east-1:123:stack/test/abc',
        'RequestId': 'test-request-id',
        'LogicalResourceId': 'GlueScriptUpload',
        'ResourceProperties': {
            'Bucket': 'bedrock-data-lake-260990198475',
            'Key': 'glue-scripts/bedrock_logs_etl.py',
        }
    }
    handler(test_event)
    print("Test passed - handler ran without errors")
