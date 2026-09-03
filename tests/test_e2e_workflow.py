import pytest
import json
import time
import secrets
import zipfile
import io
import hmac
import hashlib
from moto import mock_aws
import boto3
from src.app import lambda_handler
from src.google_wallet import create_wallet_jwt_token, verify_wallet_jwt_token
from src.apple_pass import create_apple_pass_package

SECRET_KEY = "default_merchant_jwt_secret_key_32bytes_long!"
STRIPE_SECRET = "whsec_test_stripe_secret"


def generate_stripe_header(payload: str, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


@pytest.fixture
def e2e_setup(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    monkeypatch.setenv("STAGE", "staging")
    monkeypatch.setenv("PASS_TABLE_NAME", "vegspoons_passes_staging")
    monkeypatch.setenv("IDEMPOTENCY_TABLE_NAME", "vegspoons_idempotency_staging")
    monkeypatch.setenv("SCAN_TABLE_NAME", "vegspoons_scan_audit_staging")
    monkeypatch.setenv("TEMP_BUCKET_NAME", "vegspoons-wallet-artifacts-staging")
    monkeypatch.setenv(
        "STRIPE_SECRET_ARN",
        "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:stripe",
    )
    monkeypatch.setenv(
        "MERCHANT_AUTH_SECRET_ARN",
        "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:merchant",
    )

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-2")
        pass_table = dynamodb.create_table(
            TableName="vegspoons_passes_staging",
            KeySchema=[{"AttributeName": "pass_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "pass_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        idempotency_table = dynamodb.create_table(
            TableName="vegspoons_idempotency_staging",
            KeySchema=[{"AttributeName": "stripe_event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "stripe_event_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        scan_table = dynamodb.create_table(
            TableName="vegspoons_scan_audit_staging",
            KeySchema=[
                {"AttributeName": "pass_id_timestamp", "KeyType": "HASH"}
            ],
            AttributeDefinitions=[
                {"AttributeName": "pass_id_timestamp", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        s3 = boto3.client("s3", region_name="ap-southeast-2")
        s3.create_bucket(
            Bucket="vegspoons-wallet-artifacts-staging",
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )

        secretsmanager = boto3.client("secretsmanager", region_name="ap-southeast-2")
        secretsmanager.create_secret(
            Name="arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:stripe",
            SecretString=json.dumps({"webhook_secret": STRIPE_SECRET}),
        )
        secretsmanager.create_secret(
            Name="arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:merchant",
            SecretString=json.dumps({"jwt_secret": SECRET_KEY}),
        )

        yield {
            "dynamodb": dynamodb,
            "pass_table": pass_table,
            "idempotency_table": idempotency_table,
            "scan_table": scan_table,
            "s3": s3,
        }


def test_e2e_full_workflow(e2e_setup):
    timestamp = int(time.time())

    # 1. Charge Succeeded Webhook -> Pass Created ACTIVE
    payload_charge = json.dumps({
        "id": "evt_charge_001",
        "type": "checkout.session.completed",
        "created": timestamp,
        "data": {
            "object": {
                "id": "cs_001",
                "customer": "cus_e2e_100",
                "metadata": {"tier": "GOLD"},
            }
        },
    })
    sig_charge = generate_stripe_header(payload_charge, STRIPE_SECRET, timestamp)

    res_webhook1 = lambda_handler(
        {
            "path": "/webhook",
            "httpMethod": "POST",
            "headers": {"Stripe-Signature": sig_charge},
            "body": payload_charge,
        },
        None,
    )
    assert res_webhook1["statusCode"] == 200
    assert json.loads(res_webhook1["body"])["status"] == "accepted"

    # Verify pass stored in DynamoDB
    pass_record = e2e_setup["pass_table"].get_item(Key={"pass_id": "pass_cus_e2e_100"})["Item"]
    assert pass_record["state"] == "ACTIVE"
    assert pass_record["tier"] == "GOLD"

    # 2. Duplicate Event (Idempotency check)
    res_webhook_dup = lambda_handler(
        {
            "path": "/webhook",
            "httpMethod": "POST",
            "headers": {"Stripe-Signature": sig_charge},
            "body": payload_charge,
        },
        None,
    )
    assert res_webhook_dup["statusCode"] == 200
    assert json.loads(res_webhook_dup["body"])["status"] == "already_processed"

    # 3. Apple Pass Package generation check
    pkpass = create_apple_pass_package("pass_cus_e2e_100", "E2E Member", "GOLD")
    z = zipfile.ZipFile(io.BytesIO(pkpass))
    assert "pass.json" in z.namelist()
    assert "manifest.json" in z.namelist()

    # 4. Google Wallet JWT claims verification
    nonce = secrets.token_hex(16)
    wallet_token = create_wallet_jwt_token("pass_cus_e2e_100", "GOLD", secret_key=SECRET_KEY, nonce=nonce)
    decoded = verify_wallet_jwt_token(wallet_token, secret_key=SECRET_KEY)
    assert decoded["sub"] == "pass_cus_e2e_100"
    assert decoded["tier"] == "GOLD"

    # 5. Merchant Verification - ACTIVE -> accept
    res_verify = lambda_handler(
        {
            "path": "/verify",
            "httpMethod": "POST",
            "headers": {"Authorization": "Bearer scanner_token_abc"},
            "body": json.dumps({
                "wallet_token": wallet_token,
                "scan_nonce": nonce,
                "merchant_id": "merchant_001",
                "terminal_id": "terminal_001",
            }),
        },
        None,
    )
    assert res_verify["statusCode"] == 200
    body_v = json.loads(res_verify["body"])
    assert body_v["decision"] == "accept"
    assert body_v["status"] == "ACTIVE"

    # 6. Replay Attack Detection -> deny (status 409 replayed)
    res_verify_replay = lambda_handler(
        {
            "path": "/verify",
            "httpMethod": "POST",
            "headers": {"Authorization": "Bearer scanner_token_abc"},
            "body": json.dumps({
                "wallet_token": wallet_token,
                "scan_nonce": nonce,
                "merchant_id": "merchant_001",
                "terminal_id": "terminal_001",
            }),
        },
        None,
    )
    assert res_verify_replay["statusCode"] == 409
    body_r = json.loads(res_verify_replay["body"])
    assert body_r["decision"] == "deny"
    assert body_r["reason"] == "replayed"

    # 7. Refund Webhook -> Pass state updated to REVOKED
    payload_refund = json.dumps({
        "id": "evt_charge_002",
        "type": "charge.refunded",
        "created": timestamp + 10,
        "data": {
            "object": {
                "id": "ch_001",
                "customer": "cus_e2e_100",
            }
        },
    })
    sig_refund = generate_stripe_header(payload_refund, STRIPE_SECRET, timestamp + 10)

    res_webhook_refund = lambda_handler(
        {
            "path": "/webhook",
            "httpMethod": "POST",
            "headers": {"Stripe-Signature": sig_refund},
            "body": payload_refund,
        },
        None,
    )
    assert res_webhook_refund["statusCode"] == 200

    # Verify pass updated to REVOKED in DynamoDB
    pass_record_rev = e2e_setup["pass_table"].get_item(Key={"pass_id": "pass_cus_e2e_100"})["Item"]
    assert pass_record_rev["state"] == "REVOKED"

    # 8. Verification on REVOKED pass -> deny
    nonce_new = secrets.token_hex(16)
    wallet_token_new = create_wallet_jwt_token("pass_cus_e2e_100", "GOLD", secret_key=SECRET_KEY, nonce=nonce_new)
    res_verify_rev = lambda_handler(
        {
            "path": "/verify",
            "httpMethod": "POST",
            "headers": {"Authorization": "Bearer scanner_token_abc"},
            "body": json.dumps({
                "wallet_token": wallet_token_new,
                "scan_nonce": nonce_new,
                "merchant_id": "merchant_001",
                "terminal_id": "terminal_001",
            }),
        },
        None,
    )
    assert res_verify_rev["statusCode"] == 200
    body_rev = json.loads(res_verify_rev["body"])
    assert body_rev["decision"] == "deny"
    assert body_rev["reason"] == "membership_not_active"
