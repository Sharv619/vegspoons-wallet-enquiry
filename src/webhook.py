import os
import time
from typing import Dict, Any, Tuple, Optional
from botocore.exceptions import ClientError
from src.db import get_dynamodb_resource


def check_and_claim_idempotency(stripe_event_id: str) -> bool:
    """
    Attempts to atomically claim a Stripe event ID in DynamoDB using a conditional write.
    Returns True if claimed (first time processing), False if already processed or locked.
    """
    table_name = os.environ.get("IDEMPOTENCY_TABLE_NAME", "vegspoons_idempotency_dev")
    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(table_name)

    now = int(time.time())
    ttl = now + (24 * 3600)  # 24 hour TTL

    try:
        table.put_item(
            Item={
                "stripe_event_id": stripe_event_id,
                "created_at": now,
                "ttl": ttl,
                "status": "PROCESSING",
            },
            ConditionExpression="attribute_not_exists(stripe_event_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Event already processed or in-flight
            return False
        raise e


def map_stripe_event_to_pass_state(
    event_type: str, data_object: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Maps Stripe webhook event types and data payload to internal pass attributes:
    (customer_id, pass_state, tier)
    """
    customer_id = data_object.get("customer")
    if not customer_id and "customer" in data_object:
        customer_id = data_object["customer"]

    # Fallback to customer details or email if customer string not present
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")

    if not customer_id:
        customer_id = data_object.get("id", "cust_unknown")

    state = None
    tier = "STANDARD"

    if event_type == "checkout.session.completed":
        state = "ACTIVE"
        tier = data_object.get("metadata", {}).get("tier", "VIP")
    elif event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        status = data_object.get("status")
        if status in ("active", "trialing"):
            state = "ACTIVE"
        elif status == "past_due":
            state = "PAST_DUE"
        elif status in ("canceled", "unpaid"):
            state = "EXPIRED"
        else:
            state = "PENDING"
    elif event_type == "customer.subscription.deleted":
        state = "REVOKED"
    elif event_type == "invoice.payment_succeeded":
        state = "ACTIVE"
    elif event_type == "invoice.payment_failed":
        state = "PAST_DUE"
    elif event_type == "charge.refunded":
        state = "REVOKED"

    return customer_id, state, tier
