import json
import os
import time
import jwt
from botocore.exceptions import ClientError
from src.db import get_dynamodb_resource
from src.secrets import get_secret_dict
from src.google_wallet import verify_wallet_jwt_token


def handle_verify(event: dict) -> dict:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth_header = headers.get("authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return {
            "statusCode": 401,
            "body": json.dumps(
                {
                    "decision": "deny",
                    "reason": "unauthorized_scanner",
                    "verified_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
            ),
        }

    raw_body = event.get("body", "")
    if event.get("isBase64Encoded", False):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        body = json.loads(raw_body)
    except Exception:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"decision": "deny", "reason": "malformed_request"}
            ),
        }

    wallet_token = body.get("wallet_token")
    scan_nonce = body.get("scan_nonce")
    merchant_id = body.get("merchant_id", "merchant_unknown")
    terminal_id = body.get("terminal_id", "terminal_unknown")

    if not wallet_token or not scan_nonce:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"decision": "deny", "reason": "missing_token_or_nonce"}
            ),
        }

    # Retrieve auth secrets
    merchant_secret_arn = os.environ.get("MERCHANT_AUTH_SECRET_ARN", "")
    secret_key = "default_merchant_jwt_secret_key_32bytes_long!"
    if merchant_secret_arn:
        try:
            sec = get_secret_dict(merchant_secret_arn)
            secret_key = sec.get("jwt_secret", secret_key)
        except Exception:
            pass

    # Validate wallet token
    try:
        decoded_token = verify_wallet_jwt_token(
            wallet_token, secret_key=secret_key
        )
    except jwt.ExpiredSignatureError:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "decision": "deny",
                    "status": "EXPIRED",
                    "reason": "token_expired",
                    "verified_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
            ),
        }
    except jwt.PyJWTError:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "decision": "deny",
                    "reason": "invalid_token_signature",
                    "verified_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
            ),
        }

    pass_id = decoded_token.get("sub")

    # Read canonical state from DynamoDB
    pass_table_name = os.environ.get("PASS_TABLE_NAME", "vegspoons_passes_dev")
    dynamodb = get_dynamodb_resource()
    pass_table = dynamodb.Table(pass_table_name)

    pass_record = pass_table.get_item(Key={"pass_id": pass_id}).get("Item")

    if not pass_record:
        return {
            "statusCode": 404,
            "body": json.dumps(
                {
                    "decision": "deny",
                    "reason": "pass_not_found",
                    "verified_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
            ),
        }

    pass_state = pass_record.get("state", "UNKNOWN")

    if pass_state != "ACTIVE":
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "decision": "deny",
                    "status": pass_state,
                    "reason": "membership_not_active",
                    "verified_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    ),
                }
            ),
        }

    # Record scan and verify nonce uniqueness for replay protection
    scan_table_name = os.environ.get(
        "SCAN_TABLE_NAME", "vegspoons_scan_audit_dev"
    )
    scan_table = dynamodb.Table(scan_table_name)
    now_ts = int(time.time())
    pass_timestamp_key = f"{pass_id}#{now_ts}#{scan_nonce}"

    try:
        scan_table.put_item(
            Item={
                "pass_id_timestamp": pass_timestamp_key,
                "pass_id": pass_id,
                "scan_nonce": scan_nonce,
                "merchant_id": merchant_id,
                "terminal_id": terminal_id,
                "scanned_at": now_ts,
            },
            ConditionExpression="attribute_not_exists(pass_id_timestamp)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return {
                "statusCode": 409,
                "body": json.dumps(
                    {
                        "decision": "deny",
                        "reason": "replayed",
                        "verified_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    }
                ),
            }
        raise e

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "decision": "accept",
                "status": "ACTIVE",
                "pass_id": pass_id,
                "member_display": "Active VegSpoons Member",
                "verified_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "decision_ttl_seconds": 30,
            }
        ),
    }
