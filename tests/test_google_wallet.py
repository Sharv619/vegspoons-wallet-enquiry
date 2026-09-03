import pytest
import secrets
import jwt
from src.google_wallet import (
    generate_google_wallet_payload,
    create_wallet_jwt_token,
    verify_wallet_jwt_token,
)


def test_generate_google_wallet_payload():
    payload = generate_google_wallet_payload("pass_456", "John Doe", "VIP")
    assert payload["aud"] == "google"
    assert (
        payload["payload"]["genericObjects"][0]["barcode"]["value"]
        == "pass_456"
    )
    assert (
        payload["payload"]["genericObjects"][0]["header"]["defaultValue"][
            "value"
        ]
        == "John Doe"
    )


def test_create_and_verify_wallet_jwt():
    secret = "secret_key_123_must_be_32_bytes_long_key"
    nonce = secrets.token_hex(16)
    token = create_wallet_jwt_token(
        "pass_456", "VIP", secret_key=secret, nonce=nonce
    )

    assert isinstance(token, str)
    assert len(token) > 0

    decoded = verify_wallet_jwt_token(token, secret_key=secret)
    assert decoded["sub"] == "pass_456"
    assert decoded["nonce"] == nonce
    assert decoded["tier"] == "VIP"


def test_verify_expired_jwt():
    secret = "secret_key_123_must_be_32_bytes_long_key"
    nonce = secrets.token_hex(16)
    # Create expired token
    token = create_wallet_jwt_token(
        "pass_456", "VIP", secret_key=secret, nonce=nonce, ttl_seconds=-10
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        verify_wallet_jwt_token(token, secret_key=secret)
