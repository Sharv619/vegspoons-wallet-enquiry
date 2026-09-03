# VegSpoons Wallet Bridge - Developer Guide

## Overview
The VegSpoons Wallet Bridge is an AWS SAM serverless sidecar for issuing Apple & Google Wallet passes from Stripe payment events and conducting sub-200ms merchant scan verifications.

## Prerequisites
- Python 3.12+
- AWS CLI
- AWS SAM CLI

## Quickstart

1. Create a virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

2. Run local tests with Pytest and Moto:
```bash
pytest
```

3. Build with SAM:
```bash
sam build
```

4. Run API locally:
```bash
sam local start-api
```

## Architecture & Naming Conventions
- Region: `ap-southeast-2` (Sydney) strictly.
- Stack Name: `vegspoons-wallet-bridge-{env}`
- DynamoDB Tables: `vegspoons_passes_{env}`, `vegspoons_idempotency_{env}`, `vegspoons_scan_audit_{env}`
- S3 Bucket: `vegspoons-wallet-artifacts-{account_id}-{region}`
