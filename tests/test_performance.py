import pytest
import time
import secrets
from moto import mock_aws
import boto3
from src.app import lambda_handler
from src.google_wallet import create_wallet_jwt_token

SECRET_KEY = "default_merchant_jwt_secret_key_32bytes_long!"


@pytest.fixture
def perf_setup(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    monkeypatch.setenv("STAGE", "dev")
    monkeypatch.setenv("PASS_TABLE_NAME", "vegspoons_passes_dev")
    monkeypatch.setenv("SCAN_TABLE_NAME", "vegspoons_scan_audit_dev")

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        pass_table = dynamodb.create_table(
            TableName="vegspoons_passes_dev",
            KeySchema=[{"AttributeName": "pass_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pass_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.create_table(
            TableName="vegspoons_scan_audit_dev",
            KeySchema=[{"AttributeName": "pass_id_timestamp", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "pass_id_timestamp", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        pass_table.put_item(
            Item={
                "pass_id": "pass_perf_01",
                "customer_id": "cus_perf",
                "state": "ACTIVE",
                "tier": "VIP",
            }
        )
        yield dynamodb


def test_verify_latency_benchmark(perf_setup):
    iterations = 20
    latencies = []

    for i in range(iterations):
        nonce = secrets.token_hex(16)
        token = create_wallet_jwt_token(
            "pass_perf_01", "VIP", secret_key=SECRET_KEY, nonce=nonce
        )

        event = {
            "path": "/verify",
            "httpMethod": "POST",
            "headers": {"Authorization": "Bearer scanner_token_abc"},
            "body": json_dumps_fast(token, nonce),
        }

        start = time.perf_counter()
        response = lambda_handler(event, None)
        end = time.perf_counter()

        assert response["statusCode"] == 200
        latencies.append((end - start) * 1000)  # ms

    avg_latency = sum(latencies) / len(latencies)
    assert (
        avg_latency < 50
    ), f"Average verification latency {avg_latency:.2f}ms exceeded 50ms budget"


def json_dumps_fast(token, nonce):
    import json

    return json.dumps(
        {
            "wallet_token": token,
            "scan_nonce": nonce,
            "merchant_id": "m_perf",
            "terminal_id": "t_perf",
        }
    )
