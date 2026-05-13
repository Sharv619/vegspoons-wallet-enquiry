# Product Requirements Document: VegSpoons Wallet Bridge

## Executive Summary

VegSpoons needs a mobile-native membership verification experience without destabilizing the existing directory site. The VegSpoons Wallet Bridge is a Python 3.12 AWS Lambda sidecar that converts trusted Stripe payment events into Apple Wallet and Google Wallet membership passes. It also provides real-time merchant verification so screenshots and stale passes cannot be used as proof of membership.

## Problem Statement

The current VegSpoons directory site runs on a legacy Apache, Ubuntu, and jQuery stack with an existing membership system. The site can represent membership status, but it does not provide native wallet passes and it is exposed to screenshot-based fraud. A static image of a member page or outdated proof screen can be reused at a merchant location without server-side validation.

## Product Goals

- Issue wallet-native membership passes after valid Stripe payment or subscription events.
- Provide merchants with live membership verification at scan time.
- Eliminate reliance on screenshots as proof of eligibility.
- Avoid direct changes to the legacy site codebase, database schema, and deployment workflow.
- Keep sensitive payment, pass signing, and verification data inside the AWS Sydney region.

## Non-Goals

- Replace the existing directory site or membership portal.
- Rebuild the legacy membership database.
- Store full payment card data.
- Build a general-purpose CRM.
- Operate outside `ap-southeast-2` for production traffic.

## Sidecar Philosophy: Zero-Interference With Legacy Code

The wallet bridge must operate beside the existing site, not inside it. The legacy application remains the browsing, account, and directory experience. The sidecar consumes payment lifecycle events from Stripe and maintains its own minimal verification state.

Sidecar rules:

- No direct writes to the legacy application database.
- No dependency on legacy application deployment cycles.
- No changes required to Apache, jQuery, PHP, or existing hosting configuration.
- No shared runtime secrets with the legacy site.
- No introduction of wallet-specific logic into legacy templates.
- Integration occurs through Stripe webhooks, wallet delivery links, and documented API boundaries.

This approach reduces migration risk, limits blast radius, and allows the wallet capability to be deployed, rolled back, or scaled independently.

## Users And Stakeholders

| Role | Need |
| --- | --- |
| VegSpoons member | Add a valid membership pass to Apple Wallet or Google Wallet. |
| Merchant staff | Scan a pass and receive a fast accept or deny decision. |
| VegSpoons operations | Reissue, revoke, and audit passes without touching legacy infrastructure. |
| Finance/admin team | Ensure wallet eligibility follows Stripe payment status. |
| Security owner | Keep signing keys, payment secrets, and verification state protected. |

## Functional Requirements

### FR1: Stripe Webhook Validation

- The service must accept Stripe webhooks at `POST /webhook`.
- The service must verify the `Stripe-Signature` header against the raw request body.
- The service must enforce timestamp tolerance to reduce replay risk.
- Invalid signatures must be rejected before payload parsing or business logic.
- Duplicate Stripe events must be handled idempotently using `event.id`.

### FR2: Membership State Mapping

- The service must map Stripe customer, checkout, invoice, and subscription events to internal pass state.
- Supported states must include `PENDING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`, `REVOKED`, and `SUSPENDED`.
- Payment success must activate or renew membership eligibility.
- Failed payment, cancellation, refund, or explicit admin action must remove or downgrade eligibility.

### FR3: Cryptographic Pass Signing

- The service must generate Apple Wallet `.pkpass` packages with signed manifests.
- The service must generate Google Wallet JWTs or object updates using a controlled service account.
- Apple certificates, Google service account credentials, and signing keys must be read from Secrets Manager.
- Pass artifacts must be integrity protected and must not expose sensitive payment data.

### FR4: Wallet JWT Generation

- The service must generate signed wallet and verification tokens.
- JWTs must include issuer, audience, subject, issued-at, expiry, token ID, and nonce claims.
- Nonces must use at least 128 bits of cryptographic entropy.
- JWTs must have short expiries when used for scan verification.
- Tokens must be signed with an approved asymmetric algorithm such as ES256 or RS256 unless platform constraints require otherwise.

### FR5: Pass Delivery

- The service must store temporary pass delivery artifacts in S3.
- S3 objects must use private ACLs, encryption at rest, and lifecycle expiry.
- Delivery links must be short-lived and scoped to a single pass artifact.
- Delivery artifacts must be regenerated rather than permanently exposed.

### FR6: Live Merchant Verification

- The service must expose `POST /verify` for merchant scans.
- The service must authenticate the merchant scanner.
- The service must verify wallet token signature, expiry, audience, issuer, and nonce structure.
- The service must read current pass status from DynamoDB at scan time.
- The service must return `accept`, `deny`, or `review` with a reason code.
- The service must detect replayed scan nonces through conditional writes.

### FR7: State Tracking And Auditability

- The service must persist current pass state in DynamoDB.
- The service must record idempotency decisions for webhook events.
- The service must record scan outcomes for fraud analysis.
- Audit records must avoid raw secrets, payment card data, and unnecessary personally identifiable information.

### FR8: Operational Observability

- The service must emit structured logs.
- Logs must include correlation IDs, Stripe event IDs, pass IDs, and merchant IDs where applicable.
- Metrics must include webhook acceptance rate, verification latency, denial rate, replay detection, Lambda errors, and throttles.
- Alerts must exist for elevated fraud signals, elevated 5xx rates, and latency budget breaches.

## Non-Functional Requirements

### Performance

- `/verify` must return a decision in less than 200 ms p95 under normal regional load.
- `/webhook` must acknowledge accepted events in less than 200 ms p95 after warm start.
- Cold starts must be minimized through small deployment packages, client reuse, and no unnecessary VPC attachment.
- The design must support bursty Stripe webhook retries without duplicate pass issuance.

### Security

- The service must follow a security-first model aligned with ISO/IEC 27001 control intent.
- No secret values may be stored in Lambda environment variables.
- Secrets must reside in AWS Secrets Manager and be encrypted with KMS.
- All signing keys must have rotation and revocation procedures.
- Wallet tokens must be signed and time-bounded.
- API Gateway must enforce TLS.
- Logs must redact secrets, signatures, wallet tokens, and payment data.
- IAM roles must use least privilege and resource-level permissions.

### Regional Data Compliance

- Production resources must be deployed in `ap-southeast-2`.
- DynamoDB tables, S3 buckets, Lambda functions, Secrets Manager secrets, API Gateway APIs, and CloudWatch logs must remain in Sydney.
- Cross-region replication must be disabled unless approved through a formal data residency exception.

### Reliability

- Stripe webhook processing must be idempotent.
- Verification must fail closed when token signature validation fails.
- Verification may return `review` instead of `accept` when required state is temporarily unavailable.
- DynamoDB point-in-time recovery must be enabled for production tables.
- S3 temporary artifacts must be recoverable through regeneration from DynamoDB state and signing secrets.

### Scalability

- The service must scale horizontally through Lambda concurrency.
- DynamoDB capacity mode should be on-demand for launch unless predictable traffic justifies provisioned capacity.
- Hot partitions must be avoided by using high-cardinality pass IDs and event IDs.
- Verification workloads must be stateless at the Lambda runtime level.

### Maintainability

- Pass generation, Stripe event mapping, token signing, and verification decisions must be modularized.
- Business decision codes must be explicit and testable.
- The deployment stack must be reproducible through SAM or CDK.
- Documentation must include API contracts, deployment instructions, and operational runbooks.

## Acceptance Criteria

- A valid Stripe test payment results in an active wallet pass state.
- Duplicate Stripe event delivery does not create duplicate passes.
- An invalid Stripe signature is rejected before payload parsing.
- Apple pass generation produces a signed `.pkpass` accepted by Apple Wallet tooling.
- Google Wallet payload generation produces a valid signed JWT or object update.
- A live active pass scan returns `accept`.
- A revoked, expired, malformed, or replayed scan returns `deny`.
- p95 verification latency remains below 200 ms in `ap-southeast-2` during launch-load testing.
- No secret values appear in Lambda environment variables, logs, deployment outputs, or source control.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Stripe webhook replay or duplicate delivery | Duplicate pass issuance | HMAC validation, timestamp tolerance, DynamoDB conditional idempotency writes |
| Screenshot fraud | Merchant accepts inactive membership | Live `/verify` decision based on DynamoDB state and signed wallet token |
| Key leakage | Pass forgery or API compromise | Secrets Manager, KMS, IAM least privilege, log redaction, rotation runbook |
| Cold starts | Slow merchant scan experience | Python 3.12, small package, client reuse, provisioned concurrency if required |
| Regional drift | Compliance breach | Region guardrails in infrastructure code and deployment process |
| Apple/Google signing errors | Pass delivery failure | Deterministic signing tests and staging wallet validation |

## Launch Readiness Checklist

- Production stack deployed in `ap-southeast-2`.
- Stripe webhook endpoint configured with production endpoint secret.
- Apple and Google wallet credentials stored in Secrets Manager.
- DynamoDB PITR enabled.
- S3 block public access and lifecycle expiry enabled.
- API Gateway throttling and access logs enabled.
- CloudWatch alarms configured.
- Security review completed.
- Load test confirms `/verify` p95 below 200 ms.
- Runbook and rollback procedure approved.

