import pytest
import json
import secrets
from moto import mock_aws
import boto3
from src.app import lambda_handler
from src.google_wallet import create_wallet_jwt_token

SECRET_KEY = "default_merchant_jwt_secret_key_32bytes_long!"


@pytest.fixture
def aws_verify_setup(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    monkeypatch.setenv("STAGE", "dev")
    monkeypatch.setenv("PASS_TABLE_NAME", "vegspoons_passes_dev")
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "vegspoons_idempotency_dev")
    monkeypatch.setenv("SCAN_TABLE_NAME", "vegspoons_scan_audit_dev")
    monkeypatch.setenv(
        "MERCHANT_AUTH_SECRET_ARN",
        "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:merchant",
    )

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        pass_table = dynamodb.create_table(
            TableName="vegspoons_passes_dev",
            KeySchema=[{"AttributeName": "pass_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "pass_id", "AttributeType": "S"}
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

        # Seed passes
        pass_table.put_item(
            Item={
                "pass_id": "pass_active_01",
                "customer_id": "cus_1",
                "state": "ACTIVE",
                "tier": "VIP",
            }
        )
        pass_table.put_item(
            Item={
                "pass_id": "pass_revoked_01",
                "customer_id": "cus_2",
                "state": "REVOKED",
                "tier": "STANDARD",
            }
        )

        yield dynamodb


def test_verify_unauthorized_scanner(aws_verify_setup):
    event = {
        "path": "/verify",
        "httpMethod": "POST",
        "headers": {},
        "body": json.dumps({"wallet_token": "abc", "scan_nonce": "123"}),
    }
    response = lambda_handler(event, None)
    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["decision"] == "deny"


def test_verify_active_pass_accept(aws_verify_setup):
    nonce = secrets.token_hex(16)
    token = create_wallet_jwt_token(
        "pass_active_01", "VIP", secret_key=SECRET_KEY, nonce=nonce
    )

    event = {
        "path": "/verify",
        "httpMethod": "POST",
        "headers": {"Authorization": "Bearer scanner_token_abc"},
        "body": json.dumps(
            {
                "wallet_token": token,
                "scan_nonce": nonce,
                "merchant_id": "m_1",
                "terminal_id": "t_1",
            }
        ),
    }

    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["decision"] == "accept"
    assert body["status"] == "ACTIVE"


def test_verify_revoked_pass_deny(aws_verify_setup):
    nonce = secrets.token_hex(16)
    token = create_wallet_jwt_token(
        "pass_revoked_01", "STANDARD", secret_key=SECRET_KEY, nonce=nonce
    )

    event = {
        "path": "/verify",
        "httpMethod": "POST",
        "headers": {"Authorization": "Bearer scanner_token_abc"},
        "body": json.dumps(
            {
                "wallet_token": token,
                "scan_nonce": nonce,
                "merchant_id": "m_1",
                "terminal_id": "t_1",
            }
        ),
    }

    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["decision"] == "deny"
    assert body["reason"] == "membership_not_active"
