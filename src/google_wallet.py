import time
import jwt
from typing import Dict, Any


def generate_google_wallet_payload(
    pass_id: str,
    member_name: str,
    tier: str,
    issuer_id: str = "3388000000022334455",
) -> Dict[str, Any]:
    """
    Generates Google Wallet REST object structure for GenericPass.
    """
    class_id = f"{issuer_id}.vegspoons_membership"
    object_id = f"{issuer_id}.{pass_id}"

    return {
        "iss": "vegspoons-service-account@vegspoons.iam.gserviceaccount.com",
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "payload": {
            "genericObjects": [
                {
                    "id": object_id,
                    "classId": class_id,
                    "state": "ACTIVE",
                    "cardTitle": {
                        "defaultValue": {
                            "language": "en-US",
                            "value": "VegSpoons Member",
                        }
                    },
                    "header": {
                        "defaultValue": {
                            "language": "en-US",
                            "value": member_name,
                        }
                    },
                    "subplots": [
                        {
                            "title": {
                                "defaultValue": {
                                    "language": "en-US",
                                    "value": "Tier",
                                }
                            },
                            "subtitle": {
                                "defaultValue": {
                                    "language": "en-US",
                                    "value": tier,
                                }
                            },
                        }
                    ],
                    "barcode": {
                        "type": "QR_CODE",
                        "value": pass_id,
                    },
                }
            ]
        },
    }


def create_wallet_jwt_token(
    pass_id: str,
    tier: str,
    secret_key: str,
    nonce: str,
    issuer: str = "VegSpoonsWalletBridge",
    audience: str = "MerchantScanner",
    ttl_seconds: int = 300,
) -> str:
    """
    Creates a signed Wallet Verification JWT containing entropy nonce, pass ID, tier, and short expiry.
    """
    now = int(time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": pass_id,
        "jti": f"token_{nonce}",
        "iat": now,
        "exp": now + ttl_seconds,
        "nonce": nonce,
        "tier": tier,
    }

    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token


def verify_wallet_jwt_token(
    token: str,
    secret_key: str,
    expected_issuer: str = "VegSpoonsWalletBridge",
    expected_audience: str = "MerchantScanner",
) -> Dict[str, Any]:
    """
    Verifies and decodes a Wallet JWT token.
    Raises jwt.PyJWTError on invalid/expired signatures or mismatch.
    """
    decoded = jwt.decode(
        token,
        secret_key,
        algorithms=["HS256"],
        issuer=expected_issuer,
        audience=expected_audience,
    )
    return decoded
