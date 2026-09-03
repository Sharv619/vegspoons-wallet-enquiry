import pytest
import json
import secrets
from moto import mock_aws
import boto3
from src.app import lambda_handler
from src.google_wallet import create_wallet_jwt_token

SECRET_KEY = "default_merchant_jwt_secret_key_32bytes_long!"


@pytest.fixture
def aws_replay_setup(monkeypatch):
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
                "pass_id": "pass_active_replay",
                "customer_id": "cus_99",
                "state": "ACTIVE",
                "tier": "GOLD",
            }
        )

        yield dynamodb


def test_replay_attack_detection(aws_replay_setup):
    nonce = secrets.token_hex(16)
    token = create_wallet_jwt_token(
        "pass_active_replay", "GOLD", secret_key=SECRET_KEY, nonce=nonce
    )

    event = {
        "path": "/verify",
        "httpMethod": "POST",
        "headers": {"Authorization": "Bearer scanner_token_abc"},
        "body": json.dumps(
            {
                "wallet_token": token,
                "scan_nonce": nonce,
                "merchant_id": "m_100",
                "terminal_id": "t_200",
            }
        ),
    }

    # First scan - expect ACCEPT
    res1 = lambda_handler(event, None)
    assert res1["statusCode"] == 200
    body1 = json.loads(res1["body"])
    assert body1["decision"] == "accept"

    # Replayed scan with same pass and nonce within same second - expect DENY with "replayed"
    res2 = lambda_handler(event, None)
    assert res2["statusCode"] == 409
    body2 = json.loads(res2["body"])
    assert body2["decision"] == "deny"
    assert body2["reason"] == "replayed"
