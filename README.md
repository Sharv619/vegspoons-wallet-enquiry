# VegSpoons Wallet Bridge

High-performance serverless sidecar for issuing Apple Wallet and Google Wallet membership passes from Stripe payment events, with a live merchant verification loop.

## Documentation Suite

- [Product Requirements Document](./docs/PRD.md)
- [Mermaid Workflow Diagram](./docs/workflow.md)
- [Standalone Mermaid Source](./docs/mermaid.md)
- [Accelerated 10-Day Technical Work Breakdown Structure](./docs/WBS.md)
- [Sovereign Membership Engine Proposal With 30-Day Roadmap](./docs/sovereign-membership-engine-proposal.md)

## System Overview

The VegSpoons Wallet Bridge is designed as a zero-interference sidecar around the existing VegSpoons directory site. The legacy Apache, Ubuntu, and jQuery membership stack continues to operate without schema changes, runtime coupling, or deployment dependency on the wallet service.

The bridge listens to Stripe webhooks, validates event authenticity, records membership state in DynamoDB, generates wallet pass artifacts, stores short-lived delivery assets in S3, and exposes a verification API for merchant scans. Wallet passes are not treated as static images. Each scan resolves to live server-side state so screenshots, stale passes, and replayed QR codes can be rejected.

## Reference Architecture

- API Gateway REST API exposes `POST /webhook` and `POST /verify`.
- Python 3.12 AWS Lambda contains the logic engine, pass factory, and verification handler.
- AWS Secrets Manager stores Stripe, Apple, and Google signing material.
- DynamoDB stores idempotency records, wallet pass state, entitlement status, and scan audit records.
- S3 stores temporary pass packages and delivery payloads with strict lifecycle expiry.
- CloudWatch Logs, Metrics, and Alarms provide operational visibility.
- All resources are deployed in `ap-southeast-2` to keep customer and membership verification data region-locked to Sydney.

## Design Principles

- **Sidecar isolation:** no direct writes to the legacy site database and no required changes to Apache, PHP, jQuery, or hosting topology.
- **Stateless execution:** Lambda handlers derive state from signed inputs, DynamoDB, and Secrets Manager, keeping runtime instances disposable.
- **Idempotency by default:** Stripe event IDs and internal pass IDs are written with DynamoDB conditional expressions to prevent duplicate issuance.
- **Security-first pass handling:** wallet tokens are signed, scan results are live, screenshots are insufficient for acceptance, and replay attempts are auditable.
- **No secret values in environment variables:** Lambda environment variables may contain secret ARNs and configuration names only.
- **Low-latency verification:** `/verify` is optimized for sub-200 ms p95 decision time in-region.

## Core Data Stores

| Store | Purpose | Suggested key design |
| --- | --- | --- |
| `WalletBridgePasses` | Canonical pass and entitlement state | `PK = PASS#<pass_id>`, `SK = STATE#CURRENT` |
| `WalletBridgeIdempotency` | Stripe webhook deduplication and pass factory locks | `PK = STRIPE_EVENT#<event_id>` with TTL |
| `WalletBridgeScans` | Merchant scan audit trail and replay detection | `PK = PASS#<pass_id>`, `SK = SCAN#<timestamp>#<nonce>` |
| S3 temporary bucket | Apple `.pkpass`, Google delivery JSON, and short-lived artifacts | Lifecycle expiry between 15 minutes and 24 hours |

## Prerequisites

- AWS account with deployment access to `ap-southeast-2`.
- AWS CLI configured for the target account.
- AWS SAM CLI or AWS CDK installed.
- Python 3.12 available locally.
- Stripe webhook endpoint secret.
- Apple Wallet pass certificate, private key, WWDR certificate, team ID, pass type ID.
- Google Wallet issuer ID and service account JSON with the minimum required wallet permissions.

## Configuration

Secrets must be created in AWS Secrets Manager before production deployment. Lambda should receive only ARNs or secret names.

Recommended secrets:

| Secret | Contents |
| --- | --- |
| `vegspoons/prod/stripe` | Stripe API key and webhook endpoint secret |
| `vegspoons/prod/apple-wallet` | Apple pass certificate bundle, private key material, certificate password, team metadata |
| `vegspoons/prod/google-wallet` | Google Wallet issuer ID and service account JSON |
| `vegspoons/prod/merchant-auth` | Scanner JWT issuer key material or public key set |

Recommended non-secret environment variables:

| Variable | Example | Notes |
| --- | --- | --- |
| `AWS_REGION` | `ap-southeast-2` | Must match deployment region |
| `STAGE` | `prod` | Used for table and bucket names |
| `STRIPE_SECRET_ARN` | `arn:aws:secretsmanager:...` | ARN only, not secret value |
| `APPLE_SECRET_ARN` | `arn:aws:secretsmanager:...` | ARN only |
| `GOOGLE_SECRET_ARN` | `arn:aws:secretsmanager:...` | ARN only |
| `PASS_TABLE_NAME` | `WalletBridgePasses-prod` | DynamoDB table name |
| `IDEMPOTENCY_TABLE_NAME` | `WalletBridgeIdempotency-prod` | DynamoDB table name |
| `SCAN_TABLE_NAME` | `WalletBridgeScans-prod` | DynamoDB table name |
| `TEMP_BUCKET_NAME` | `vegspoons-wallet-temp-prod` | S3 bucket name |

## Deployment With AWS SAM

The exact template may vary, but the production deployment should follow this flow:

```bash
sam build --use-container
sam deploy --guided --region ap-southeast-2
```

Recommended guided values:

```text
Stack Name: vegspoons-wallet-bridge-prod
AWS Region: ap-southeast-2
Confirm changes before deploy: true
Allow SAM CLI IAM role creation: true
Save arguments to configuration file: true
```

Production deployment guardrails:

- Reject deployment outside `ap-southeast-2`.
- Enable S3 block public access and default SSE-KMS or SSE-S3 encryption.
- Enable DynamoDB point-in-time recovery.
- Scope Lambda IAM permissions to specific secret ARNs, table ARNs, and bucket prefixes.
- Enable API Gateway access logs without request bodies or wallet tokens.

## Deployment With AWS CDK

If CDK is preferred:

```bash
cdk bootstrap aws://<account-id>/ap-southeast-2
cdk deploy VegSpoonsWalletBridgeProd --region ap-southeast-2
```

The CDK stack should synthesize:

- API Gateway REST API with stage-specific throttling.
- Lambda function using Python 3.12 runtime.
- DynamoDB tables with encryption and PITR.
- S3 bucket with lifecycle expiry and no public access.
- Secrets Manager read permissions limited to required secret ARNs.
- CloudWatch alarms for error rate, p95 latency, throttles, and verification denials.

## API Documentation

### `POST /webhook`

Receives Stripe webhook events and starts wallet issuance or membership state updates.

#### Request

Headers:

| Header | Required | Description |
| --- | --- | --- |
| `Stripe-Signature` | Yes | Stripe HMAC signature header. Must be verified against the raw request body. |
| `Content-Type` | Yes | `application/json` |

Body:

The raw Stripe webhook payload. The handler must validate the HMAC signature before JSON parsing.

Supported event types:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `charge.refunded`

#### Processing Contract

1. Read the raw request body from API Gateway.
2. Fetch the Stripe webhook secret from Secrets Manager or the local warm-cache.
3. Verify `Stripe-Signature` using Stripe's HMAC-SHA256 signing scheme and timestamp tolerance.
4. Reject invalid, expired, malformed, or replayed signatures.
5. Write `event.id` to the idempotency table with a DynamoDB conditional put.
6. Resolve the membership identity and entitlement status from the Stripe event.
7. Generate or update the wallet pass state.
8. Sign the Apple pass package and/or Google Wallet JWT.
9. Store temporary delivery artifacts in S3 with lifecycle expiry.
10. Return a deterministic acknowledgement to Stripe.

#### Example Response

```json
{
  "received": true,
  "event_id": "evt_123",
  "status": "accepted"
}
```

#### Status Codes

| Code | Meaning |
| --- | --- |
| `200` | Event accepted or already processed idempotently. |
| `400` | Malformed payload or unsupported event structure. |
| `401` | Missing or invalid Stripe signature. |
| `409` | Event is already locked by an in-flight processor. |
| `500` | Internal error. Stripe may retry. |

### `POST /verify`

Validates a merchant scan against live wallet pass state.

#### Request

Headers:

| Header | Required | Description |
| --- | --- | --- |
| `Authorization` | Yes | Merchant scanner JWT or signed service token. |
| `Content-Type` | Yes | `application/json` |

Body:

```json
{
  "wallet_token": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...",
  "scan_nonce": "b64url-128-bit-random",
  "merchant_id": "merchant_123",
  "terminal_id": "terminal_07"
}
```

#### Processing Contract

1. Authenticate the merchant scanner token.
2. Verify the wallet token signature, expiry, issuer, audience, and nonce entropy.
3. Resolve `pass_id` and membership state from DynamoDB.
4. Reject expired, revoked, suspended, or unknown passes.
5. Detect replay by conditionally writing `scan_nonce` to the scan audit table.
6. Return an accept, deny, or review decision with a short response TTL.

#### Example Success Response

```json
{
  "decision": "accept",
  "status": "ACTIVE",
  "pass_id": "pass_01J9A2M7ZQY3R6B8N4C5D2E1F0",
  "member_display": "Active VegSpoons Member",
  "verified_at": "2026-05-13T00:00:00Z",
  "decision_ttl_seconds": 30
}
```

#### Example Denial Response

```json
{
  "decision": "deny",
  "status": "REVOKED",
  "reason": "membership_not_active",
  "verified_at": "2026-05-13T00:00:00Z"
}
```

#### Status Codes

| Code | Meaning |
| --- | --- |
| `200` | Verification completed. Check `decision`. |
| `400` | Malformed request or invalid token format. |
| `401` | Scanner authentication failed. |
| `403` | Scanner is not authorized for this merchant or location. |
| `404` | Pass was not found. |
| `409` | Replay detected or nonce already consumed. |
| `429` | Scanner or merchant exceeded rate limits. |
| `500` | Internal error. Scanner should retry once with backoff. |

## Security Model

### HMAC Signature Verification

Stripe webhook validation must be performed against the raw request body. The body must not be parsed, normalized, or reserialized before verification because any byte-level change invalidates the signature model.

Required controls:

- Use Stripe's signed timestamp and HMAC-SHA256 signature.
- Enforce a narrow timestamp tolerance, normally 300 seconds.
- Use constant-time comparison through the Stripe SDK or equivalent cryptographic primitive.
- Treat missing, malformed, expired, or mismatched signatures as authentication failures.
- Never log webhook bodies, signatures, customer payment data, or wallet tokens.

### Secrets Manager Integration

Secrets Manager is the system of record for signing material and third-party API secrets.

Required controls:

- Store secret values only in Secrets Manager.
- Use Lambda environment variables only for secret ARNs, table names, bucket names, and feature flags.
- Cache decrypted secrets in memory for warm invocations with a short TTL.
- Support `AWSCURRENT` and `AWSPREVIOUS` during key rotation windows.
- Grant `secretsmanager:GetSecretValue` only for the exact required secret ARNs.
- Encrypt secrets with AWS-managed or customer-managed KMS keys.
- Redact secret fields from structured logs and exception messages.

### Wallet Token Security

Wallet QR payloads should be signed JWTs or compact JWS tokens.

Required claims:

| Claim | Purpose |
| --- | --- |
| `iss` | VegSpoons Wallet Bridge issuer |
| `aud` | Merchant verification API |
| `sub` | Stable pass ID |
| `jti` | Unique token ID for replay analysis |
| `iat` | Issued-at timestamp |
| `exp` | Short expiry timestamp |
| `nonce` | At least 128 bits of cryptographic entropy |
| `tier` | Non-sensitive entitlement tier identifier |

JWTs must not contain payment data, full customer names, email addresses, or internal Stripe secrets.

## Performance And Operations

Targets:

- `/verify` p95 latency below 200 ms from API Gateway receipt to decision response.
- `/webhook` acknowledgement p95 below 200 ms for accepted events after warm start.
- Lambda cold start p95 below 1 second with optimized package size and no unnecessary VPC attachment.
- DynamoDB conditional writes below 20 ms p95 in-region under normal load.

Operational practices:

- Use Python 3.12 with a small dependency graph.
- Initialize SDK clients outside the handler for execution environment reuse.
- Cache Secrets Manager responses during warm invocations.
- Use DynamoDB strongly consistent reads only when required by verification correctness.
- Add CloudWatch alarms for Lambda errors, throttles, API Gateway 5xx, p95 latency, and replay spikes.
- Use structured JSON logs with correlation IDs, Stripe event IDs, pass IDs, and merchant IDs.

## Regional Compliance

The production stack must be deployed and operated in `ap-southeast-2`.

Regional controls:

- API Gateway, Lambda, DynamoDB, S3, Secrets Manager, KMS, and CloudWatch all run in Sydney.
- S3 replication is disabled unless the destination is explicitly approved.
- DynamoDB global tables are disabled unless a formal data residency exception is approved.
- Logs must not export customer-identifying data outside the region.
- Backups, exports, and incident evidence must follow the same regional boundary.

## Local Development Notes

Recommended developer loop:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
sam local start-api
```

Stripe webhook testing:

```bash
stripe listen --forward-to http://127.0.0.1:3000/webhook
stripe trigger checkout.session.completed
```

Local tests should include:

- Valid and invalid Stripe webhook signatures.
- Duplicate webhook delivery.
- Apple pass manifest signing.
- Google Wallet JWT generation.
- `/verify` accept, deny, expired, revoked, malformed, and replay cases.
- Secrets Manager failure and cache fallback behavior.
