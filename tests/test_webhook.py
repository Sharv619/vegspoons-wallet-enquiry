import pytest
import json
import time
import hmac
import hashlib
from moto import mock_aws
import boto3
from src.app import lambda_handler
from src.secrets import clear_secret_cache


def generate_stripe_header(payload: str, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


@pytest.fixture
def aws_setup(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    monkeypatch.setenv("STAGE", "dev")
    monkeypatch.setenv("PASS_TABLE_NAME", "vegspoons_passes_dev")
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "vegspoons_idempotency_dev")
    monkeypatch.setenv("SCAN_TABLE_NAME", "vegspoons_scan_audit_dev")
    monkeypatch.setenv("TEMP_BUCKET_NAME", "vegspoons-temp-dev")
    monkeypatch.setenv(
        "STRIPE_SECRET_ARN",
        "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:stripe",
    )

    clear_secret_cache()

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        dynamodb.create_table(
            TableName="vegspoons_passes_dev",
            KeySchema=[{"AttributeName": "pass_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "pass_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.create_table(
            TableName="vegspoons_idempotency_dev",
            KeySchema=[{"AttributeName": "stripe_event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "stripe_event_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.create_table(
            TableName="vegspoons_scan_audit_dev",
            KeySchema=[
                {"AttributeName": "pass_id_timestamp", "KeyType": "HASH"}
            ],
            AttributeDefinitions=[
                {"AttributeName": "pass_id_timestamp", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        secretsmanager = boto3.client("secretsmanager", region_name="ap-southeast-2")
        secretsmanager.create_secret(
            Name="arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:stripe",
            SecretString=json.dumps({"webhook_secret": "whsec_test_secret"}),
        )
        yield dynamodb
        clear_secret_cache()


def test_webhook_missing_signature(aws_setup):
    event = {
        "path": "/webhook",
        "httpMethod": "POST",
        "headers": {},
        "body": json.dumps({"type": "checkout.session.completed"}),
    }
    response = lambda_handler(event, None)
    assert response["statusCode"] == 401


def test_webhook_invalid_signature(aws_setup):
    event = {
        "path": "/webhook",
        "httpMethod": "POST",
        "headers": {"Stripe-Signature": "t=123,v1=invalid_sig"},
        "body": json.dumps({"type": "checkout.session.completed"}),
    }
    response = lambda_handler(event, None)
    assert response["statusCode"] == 401


def test_webhook_valid_signature_and_idempotency(aws_setup):
    secret = "whsec_test_secret"
    timestamp = int(time.time())
    payload = json.dumps(
        {
            "id": "evt_test123",
            "type": "checkout.session.completed",
            "created": timestamp,
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "customer": "cus_m2n3b4",
                    "metadata": {"tier": "GOLD"},
                }
            },
        }
    )

    signature = generate_stripe_header(payload, secret, timestamp)

    event = {
        "path": "/webhook",
        "httpMethod": "POST",
        "headers": {"Stripe-Signature": signature},
        "body": payload,
    }

    # First delivery
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    res_body = json.loads(response["body"])
    assert res_body["status"] == "accepted"

    # Second delivery (duplicate / idempotency test)
    response_duplicate = lambda_handler(event, None)
    assert response_duplicate["statusCode"] == 200
    res_body_dup = json.loads(response_duplicate["body"])
    assert res_body_dup["status"] == "already_processed"
