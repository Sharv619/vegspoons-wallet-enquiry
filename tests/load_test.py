import random
import time
from locust import HttpUser, task, between


class MerchantScannerUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # Sample merchant/scanner context
        self.merchant_id = f"merchant_{random.randint(100, 999)}"
        self.scanner_id = f"terminal_{random.randint(1, 20)}"
        # Mock valid token structure for load testing endpoint
        self.wallet_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJpc3MiOiJWZWdTcG9vbnNXYWxsZXRCcmlkZ2UiLCJhdWQiOiJNZXJjaGFudFNjYW5uZXIiLCJzdWIiOiJwYXNzX3BlcmZfMDEiLCJqd"
            "GkiOiJ0b2tlbl8xMjMiLCJpYXQiOjE3MDAwMDAwMDAsImV4cCI6MjAwMDAwMDAwMCwibm9uY2UiOiIxMjMiLCJ0aWVyIjoiVklQIn0."
            "signature"
        )

    @task
    def scan_pass(self):
        nonce = f"nonce_{time.time_ns()}_{random.randint(1000, 9999)}"
        headers = {
            "Authorization": "Bearer scanner_token_sample",
            "Content-Type": "application/json",
        }
        payload = {
            "wallet_token": self.wallet_token,
            "merchant_id": self.merchant_id,
            "scanner_id": self.scanner_id,
            "scan_nonce": nonce,
        }
        self.client.post("/verify", json=payload, headers=headers)
