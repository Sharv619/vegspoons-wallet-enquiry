import json
import os
from typing import Any
import stripe
from src.secrets import get_secret_dict
from src.webhook import check_and_claim_idempotency, map_stripe_event_to_pass_state
from src.db import get_dynamodb_resource


def handle_webhook(event: dict) -> dict:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    stripe_signature = headers.get("stripe-signature")

    raw_body = event.get("body", "")
    if event.get("isBase64Encoded", False):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    if not stripe_signature:
        return {
            "statusCode": 401,
            "body": json.dumps({"error": "Missing Stripe-Signature header"}),
        }

    # Retrieve Stripe webhook secret
    stripe_secret_arn = os.environ.get("STRIPE_SECRET_ARN", "")
    secret_data = {}
    if stripe_secret_arn:
        try:
            secret_data = get_secret_dict(stripe_secret_arn)
        except Exception as e:
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {"error": f"Failed to retrieve Stripe secrets: {str(e)}"}
                ),
            }

    webhook_secret = secret_data.get("webhook_secret", "whsec_test_secret")

    # Verify signature
    try:
        stripe_event = stripe.Webhook.construct_event(
            payload=raw_body,
            sig_header=stripe_signature,
            secret=webhook_secret,
        )
    except ValueError:
        return {"statusCode": 400, "body": json.dumps({"error": "Invalid payload"})}
    except stripe.SignatureVerificationError:
        return {
            "statusCode": 401,
            "body": json.dumps({"error": "Invalid Stripe signature"}),
        }

    event_dict = (
        stripe_event.to_dict() if hasattr(stripe_event, "to_dict") else stripe_event
    )
    event_id = event_dict.get("id")
    event_type = event_dict.get("type")
    data_object = event_dict.get("data", {}).get("object", {})

    # Check idempotency
    if not check_and_claim_idempotency(event_id):
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "received": True,
                    "event_id": event_id,
                    "status": "already_processed",
                }
            ),
        }

    # Map state
    customer_id, pass_state, tier = map_stripe_event_to_pass_state(
        event_type, data_object
    )

    if pass_state and customer_id:
        # Upsert pass into DynamoDB
        pass_table_name = os.environ.get("PASS_TABLE_NAME", "vegspoons_passes_dev")
        dynamodb = get_dynamodb_resource()
        table = dynamodb.Table(pass_table_name)

        pass_id = f"pass_{customer_id}"
        table.put_item(
            Item={
                "pass_id": pass_id,
                "customer_id": customer_id,
                "state": pass_state,
                "tier": tier,
                "last_event_id": event_id,
                "updated_at": event_dict.get("created"),
            }
        )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "received": True,
                "event_id": event_id,
                "status": "accepted",
            }
        ),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    path = event.get("path", "")
    http_method = event.get("httpMethod", "")

    if path == "/webhook" and http_method == "POST":
        return handle_webhook(event)
    elif path == "/verify" and http_method == "POST":
        from src.verify import handle_verify

        return handle_verify(event)

    return {
        "statusCode": 404,
        "body": json.dumps({"error": "Not Found"}),
    }
