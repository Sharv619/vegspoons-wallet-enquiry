import os
import json
import time
import boto3
from typing import Dict, Any

# In-memory secret cache: {secret_arn: (data, expiry_timestamp)}
_SECRET_CACHE: Dict[str, tuple[Dict[str, Any], float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes warm cache

_secretsmanager_client = None


def get_secretsmanager_client():
    global _secretsmanager_client
    if _secretsmanager_client is None:
        region = os.environ.get("AWS_REGION", "ap-southeast-2")
        _secretsmanager_client = boto3.client(
            "secretsmanager", region_name=region
        )
    return _secretsmanager_client


def get_secret_dict(
    secret_arn_or_name: str, force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Fetches a JSON secret from AWS Secrets Manager with warm in-memory caching.
    Supports local testing fallback if secret is mock JSON.
    """
    if not secret_arn_or_name:
        return {}

    now = time.time()
    if not force_refresh and secret_arn_or_name in _SECRET_CACHE:
        cached_data, expiry = _SECRET_CACHE[secret_arn_or_name]
        if now < expiry:
            return cached_data

    # Fetch from Secrets Manager
    client = get_secretsmanager_client()
    try:
        response = client.get_secret_value(SecretId=secret_arn_or_name)
        secret_string = response.get("SecretString", "{}")
        secret_data = json.loads(secret_string)
        _SECRET_CACHE[secret_arn_or_name] = (
            secret_data,
            now + _CACHE_TTL_SECONDS,
        )
        return secret_data
    except Exception as e:
        # If secret fetch fails, raise exception or fallback
        raise RuntimeError(
            f"Failed to fetch secret '{secret_arn_or_name}': {str(e)}"
        )


def clear_secret_cache():
    _SECRET_CACHE.clear()
