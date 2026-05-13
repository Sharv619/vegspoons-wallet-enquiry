# Work Breakdown Structure: 10-Day Bricks And Mortar Delivery Schedule

## Delivery Model

The delivery plan is structured as a 10-day build focused on foundations first, then pass generation, verification, and hardening. Each day should produce a demonstrable increment and a clear exit criterion.

## Phase 1: Infrastructure And Security, Days 1-2

### Day 1: Serverless Foundation

Tasks:

- Create SAM or CDK project structure for Python 3.12 Lambda.
- Define API Gateway REST API with `POST /webhook` and `POST /verify`.
- Define DynamoDB tables for pass state, idempotency, and scan audit.
- Define S3 temporary pass bucket with block public access and lifecycle expiry.
- Add region guardrail for `ap-southeast-2`.
- Establish structured logging format and correlation ID convention.

Deliverables:

- Deployable infrastructure skeleton.
- Initial local development instructions.
- Resource naming convention for `dev`, `staging`, and `prod`.

Exit criteria:

- Stack deploys successfully in Sydney.
- API Gateway can invoke Lambda health stubs.
- No resources deploy outside `ap-southeast-2`.

### Day 2: Security Baseline

Tasks:

- Create Secrets Manager secret contracts for Stripe, Apple Wallet, Google Wallet, and merchant auth.
- Add Lambda IAM policies with resource-level permissions.
- Add KMS encryption where required.
- Implement secret retrieval helper with warm-cache and TTL.
- Add log redaction rules for tokens, signatures, secrets, and payment data.
- Produce initial threat model for webhook replay, pass forgery, screenshot fraud, and key leakage.

Deliverables:

- Secrets Manager integration layer.
- Least-privilege IAM draft.
- Threat model and security assumptions.

Exit criteria:

- Lambda environment variables contain secret ARNs only.
- Unit tests prove secret values are not logged.
- Security owner approves the baseline control design.

## Phase 2: The Factory And Pass Generation, Days 3-5

### Day 3: Stripe Webhook Intake

Tasks:

- Implement raw body extraction from API Gateway events.
- Implement Stripe HMAC signature verification.
- Enforce timestamp tolerance and malformed header rejection.
- Add idempotency conditional writes using Stripe `event.id`.
- Map launch-critical Stripe event types to internal membership state.
- Add tests for valid, invalid, expired, and duplicate webhooks.

Deliverables:

- Functional `POST /webhook` handler.
- Webhook idempotency table writes.
- Stripe event mapping test suite.

Exit criteria:

- Invalid signatures fail closed.
- Duplicate Stripe events return deterministic success without duplicate issuance.
- Webhook acknowledgement remains within latency target for warm executions.

### Day 4: Apple Wallet Pass Factory

Tasks:

- Define Apple pass model and visual metadata.
- Generate pass manifest hashes.
- Sign `.pkpass` package using Apple certificate material from Secrets Manager.
- Embed signed verification token or barcode payload.
- Store temporary `.pkpass` artifacts in S3 with short expiry.
- Add unit and integration tests for manifest signing.

Deliverables:

- Apple Wallet pass generation module.
- S3 artifact storage path convention.
- Apple signing test fixtures.

Exit criteria:

- Generated `.pkpass` validates with Apple Wallet tooling or equivalent test harness.
- Apple private key material is never written to logs or environment variables.

### Day 5: Google Wallet And Token Issuance

Tasks:

- Define Google Wallet class and object payloads.
- Generate Google Wallet JWTs with service account credentials from Secrets Manager.
- Implement shared verification-token generation with `iss`, `aud`, `sub`, `jti`, `iat`, `exp`, and `nonce`.
- Use at least 128 bits of cryptographic entropy for nonces.
- Persist pass metadata and token metadata in DynamoDB.
- Add tests for JWT claims, expiry, signature algorithm, and malformed token rejection.

Deliverables:

- Google Wallet generation module.
- Shared wallet token signer.
- Pass state persistence layer.

Exit criteria:

- Apple and Google pass generation share a consistent pass identity model.
- Tokens contain no card data, full customer data, or Stripe secrets.

## Phase 3: Verification API And Scanner, Days 6-8

### Day 6: Live Verification Endpoint

Tasks:

- Implement `POST /verify` request validation.
- Authenticate merchant scanner JWT or signed scanner service token.
- Verify wallet token signature, issuer, audience, expiry, and nonce structure.
- Read current pass state from DynamoDB.
- Return explicit `accept`, `deny`, or `review` decisions.
- Add tests for active, expired, revoked, unknown, malformed, and unauthorized scans.

Deliverables:

- Functional `/verify` endpoint.
- Verification decision engine.
- Decision reason code catalog.

Exit criteria:

- Active pass returns `accept`.
- Invalid, expired, or revoked pass returns `deny`.
- Verification fails closed on signature failure.

### Day 7: Replay Protection And Audit Trail

Tasks:

- Implement scan nonce conditional write.
- Record scan audit events with pass ID, merchant ID, terminal ID, result, and timestamp.
- Add replay detection response path using HTTP `409`.
- Add rate limiting recommendations for API Gateway usage plans or authorizer policy.
- Add fraud metrics for replay spikes and denial anomalies.

Deliverables:

- Scan audit persistence.
- Replay detection logic.
- Fraud-oriented CloudWatch metrics.

Exit criteria:

- Reused nonce is rejected.
- Scan audit records contain enough context for investigation without storing secrets.

### Day 8: Merchant Scan Experience And Latency

Tasks:

- Build or document a minimal merchant scanner client contract.
- Optimize verification reads and conditional writes.
- Reuse AWS SDK clients outside Lambda handler.
- Cache secrets and public keys safely.
- Run load tests against `/verify` in `ap-southeast-2`.
- Tune Lambda memory, timeout, and reserved or provisioned concurrency if required.

Deliverables:

- Scanner integration guide.
- Verification load test report.
- Lambda performance tuning notes.

Exit criteria:

- `/verify` p95 latency is below 200 ms under agreed launch load.
- Cold start behavior is measured and documented.
- Scanner receives stable decision response shapes.

## Phase 4: Final Hardening And Documentation, Days 9-10

### Day 9: Production Hardening

Tasks:

- Complete security review against threat model.
- Validate IAM least privilege with access analyzer or equivalent review.
- Add alarms for Lambda errors, API Gateway 5xx, throttles, p95 latency, and replay spikes.
- Validate S3 lifecycle expiry and block public access.
- Enable DynamoDB point-in-time recovery.
- Exercise key rotation and rollback procedures in staging.

Deliverables:

- Security review notes.
- CloudWatch dashboard and alarms.
- Rotation and rollback runbook.

Exit criteria:

- No secret values appear in logs, environment variables, deployment outputs, or source control.
- Operational alarms are active.
- Rollback path is documented and tested.

### Day 10: Final Documentation And Launch Readiness

Tasks:

- Finalize PRD, technical README, API documentation, workflow diagram, and WBS.
- Document deployment steps for SAM or CDK.
- Document Stripe webhook setup.
- Document Apple and Google credential setup.
- Run final end-to-end test from Stripe event to wallet pass to merchant scan.
- Conduct launch readiness review with product, engineering, operations, and security stakeholders.

Deliverables:

- Complete documentation suite.
- End-to-end test evidence.
- Launch readiness checklist.

Exit criteria:

- Valid Stripe payment produces a wallet pass.
- Merchant scan returns a live verification decision.
- Documentation is sufficient for handover and operational support.
- Stakeholders approve production launch or identify explicit blockers.

## Cross-Cutting Workstreams

| Workstream | Runs During | Output |
| --- | --- | --- |
| Security review | Days 1-10 | Threat model, IAM review, secret handling controls |
| Test automation | Days 3-10 | Unit, integration, and replay tests |
| Observability | Days 1-10 | Logs, metrics, alarms, dashboards |
| Performance tuning | Days 6-10 | Latency report and cold start mitigation |
| Documentation | Days 1-10 | Living docs refined into final suite |

## Definition Of Done

- Infrastructure is reproducible through SAM or CDK.
- Production resources are region-locked to Sydney.
- Stripe webhooks are HMAC-verified and idempotent.
- Apple and Google passes are cryptographically signed.
- Wallet verification is live, stateless, and replay-resistant.
- Secrets are stored in Secrets Manager, not environment variables.
- `/verify` meets the sub-200 ms p95 latency target.
- Documentation and runbooks are complete enough for operations handover.

