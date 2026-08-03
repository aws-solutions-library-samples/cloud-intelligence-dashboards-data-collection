"""
Property-based tests for the Bedrock module Lambda functions.
Uses Hypothesis to validate correctness properties defined in design.md.

Each test corresponds to one of the 6 correctness properties in the design document.
Run with: pytest data-collection/deploy/tests/test_bedrock_module_properties.py -v
"""
import json
import os
from datetime import timezone
from unittest.mock import MagicMock, patch

import boto3
import botocore.exceptions
import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

# Set required env vars before importing the module
os.environ.setdefault("BUCKET_NAME", "test-bucket")
os.environ.setdefault("PREFIX", "bedrock")
os.environ.setdefault("ROLE_NAME", "test-role")

from bedrock_lambda import (  # noqa: E402
    get_last_collected,
    get_log_events,
    build_s3_key,
    build_role_arn,
    store_to_s3,
    update_marker,
    lambda_handler,
    BUCKET_NAME,
    PREFIX,
    ROLE_NAME,
    TMP_FILE,
)


# Property 1: Pagination completeness
# Feature: bedrock-module, Property 1: pagination completeness
# Validates: Requirements 3.14
@given(
    pages=st.lists(
        st.lists(
            st.fixed_dictionaries({
                "timestamp": st.integers(min_value=0),
                "message": st.text(),
                "eventId": st.text(min_size=1),
            }),
            min_size=0,
        ),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=100)
def test_pagination_completeness(pages):
    """Property 1: get_log_events yields exactly the union of all pages — no drops, no duplicates."""
    # Assign unique eventIds across all events so we can verify no drops or duplicates
    unique_pages = []
    counter = 0
    for page in pages:
        unique_page = []
        for event in page:
            unique_page.append({**event, "eventId": f"evt_{counter}"})
            counter += 1
        unique_pages.append(unique_page)

    call_count = [0]

    def mock_filter_log_events(**kwargs):
        idx = call_count[0]
        call_count[0] += 1
        response = {"events": unique_pages[idx]}
        if idx < len(unique_pages) - 1:
            response["nextToken"] = f"token_{idx + 1}"
        return response

    mock_client = MagicMock()
    mock_client.filter_log_events.side_effect = mock_filter_log_events

    collected = list(get_log_events(mock_client, "/aws/bedrock/modelinvocations", 0, 9999999999000))

    # Total count matches sum of all pages
    assert len(collected) == sum(len(page) for page in unique_pages)

    # No duplicate eventIds
    event_ids = [e["eventId"] for e in collected]
    assert len(event_ids) == len(set(event_ids))


# Property 2: JSONL format correctness
# Feature: bedrock-module, Property 2: JSONL format correctness
# Validates: Requirements 3.7
@given(
    events=st.lists(
        st.fixed_dictionaries({
            "timestamp": st.integers(min_value=0),
            "message": st.text(),
            "eventId": st.text(min_size=1),
        }),
        min_size=1,
        max_size=200,
    )
)
@settings(max_examples=100)
def test_jsonl_format_correctness(events):
    """Property 2: store_to_s3 produces a file where every line is valid JSON and line count equals event count."""
    mock_s3 = MagicMock()
    mock_s3.upload_file = MagicMock()

    store_to_s3(mock_s3, iter(events), "123456789012", "000000000000", "2024-01-01 00:00:00")

    with open(TMP_FILE, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]

    assert len(lines) == len(events)
    for line in lines:
        json.loads(line)  # raises if not valid JSON


# Property 3: S3 key path construction
# Feature: bedrock-module, Property 3: S3 key path construction
# Validates: Requirements 3.8
@given(
    account_id=st.from_regex(r"[0-9]{12}", fullmatch=True),
    payer_id=st.from_regex(r"[0-9]{12}", fullmatch=True),
    dt=st.datetimes(timezones=st.just(timezone.utc)),
)
@settings(max_examples=100)
def test_s3_key_path_construction(account_id, payer_id, dt):
    """Property 3: build_s3_key returns correct Hive-partitioned path for any account/payer/datetime."""
    result = build_s3_key(PREFIX, account_id, payer_id, dt)
    expected = (
        f"{PREFIX}/{PREFIX}-data/"
        f"payer_id={payer_id}/"
        f"year={dt.strftime('%Y')}/"
        f"month={dt.strftime('%m')}/"
        f"day={dt.strftime('%d')}/"
        f"{account_id}.json"
    )
    assert result == expected


# Property 4: Marker file round-trip
# Feature: bedrock-module, Property 4: marker file round-trip
# Validates: Requirements 3.6, 3.9
@given(end_time=st.datetimes(timezones=st.just(timezone.utc)))
@settings(max_examples=100)
def test_marker_round_trip(end_time):
    """Property 4: update_marker then get_last_collected returns original datetime to second precision."""
    # In-memory S3 mock using a dict store
    store = {}

    class MockBody:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

    class MockS3:
        exceptions = MagicMock()

        def put_object(self, Bucket, Key, Body):
            store[(Bucket, Key)] = Body.encode("utf-8") if isinstance(Body, str) else Body

        def get_object(self, Bucket, Key):
            key = (Bucket, Key)
            if key not in store:
                error_response = {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}
                raise botocore.exceptions.ClientError(error_response, "GetObject")
            return {"Body": MockBody(store[key])}

    mock_s3 = MockS3()
    mock_s3.exceptions.NoSuchKey = botocore.exceptions.ClientError

    update_marker(mock_s3, "123456789012", end_time)
    recovered = get_last_collected(mock_s3, "123456789012")

    # Design spec: round-trip preserves datetime to second precision
    # isoformat() may preserve microseconds; compare at second granularity
    assert recovered is not None
    assert recovered.replace(microsecond=0) == end_time.replace(microsecond=0)


# Property 5: AccessDenied isolation
# Feature: bedrock-module, Property 5: AccessDenied isolation
# Validates: Requirements 3.11
@given(error_code=st.sampled_from(["AccessDenied", "AccessDeniedException"]))
@settings(max_examples=100)
def test_access_denied_isolation(error_code):
    """Property 5: lambda_handler returns None without raising for any AccessDenied error code."""
    event = {
        "account": json.dumps({
            "account_id": "123456789012",
            "account_name": "test",
            "payer_id": "000000000000",
        })
    }

    error_response = {"Error": {"Code": error_code, "Message": "Access Denied"}}
    client_error = botocore.exceptions.ClientError(error_response, "AssumeRole")

    mock_sts = MagicMock()
    mock_sts.assume_role.side_effect = client_error

    def mock_boto3_client(service, **kwargs):
        if service == "sts":
            return mock_sts
        return MagicMock()

    # Provide a real-ish session that returns a known region and partition
    real_session = boto3.session.Session()

    def mock_session_factory():
        m = MagicMock()
        m.region_name = "us-east-1"
        m.get_partition_for_region.return_value = "aws"
        return m

    with patch("boto3.client", side_effect=mock_boto3_client), \
         patch("boto3.session.Session", side_effect=mock_session_factory):
        result = lambda_handler(event, None)

    assert result is None


# Property 6: Partition-aware ARN construction
# Feature: bedrock-module, Property 6: partition-aware ARN construction
# Validates: Requirements 3.4
@given(
    region=st.sampled_from([
        # aws partition
        "us-east-1", "us-east-2", "us-west-1", "us-west-2",
        "ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "ap-northeast-2",
        "ap-south-1", "eu-west-1", "eu-west-2", "eu-west-3",
        "eu-central-1", "eu-north-1", "sa-east-1", "ca-central-1",
        # aws-cn partition
        "cn-north-1", "cn-northwest-1",
        # aws-us-gov partition
        "us-gov-east-1", "us-gov-west-1",
    ])
)
@settings(max_examples=100)
def test_arn_partition_correctness(region):
    """Property 6: build_role_arn uses the correct partition for all known AWS regions."""
    arn = build_role_arn("123456789012", "test-role", region)
    expected_partition = boto3.session.Session().get_partition_for_region(region)

    assert arn.startswith(f"arn:{expected_partition}:iam::")
    assert arn.endswith(":role/test-role")
