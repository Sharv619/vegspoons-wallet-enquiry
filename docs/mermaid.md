```mermaid
sequenceDiagram
    autonumber
    actor Member
    participant Stripe
    participant APIGW as API Gateway REST
    participant Lambda as Python 3.12 Lambda Logic Engine
    participant Secrets as AWS Secrets Manager
    participant DDB as DynamoDB State Tables
    participant S3 as S3 Temporary Pass Storage
    participant Wallet as Apple/Google Wallet
    actor Merchant
    participant Verify as /verify Endpoint

    Member->>Stripe: Completes payment or subscription renewal
    Stripe->>APIGW: POST /webhook with Stripe-Signature
    APIGW->>Lambda: Forward raw body and headers
    Lambda->>Secrets: Fetch Stripe webhook secret by ARN
    Secrets-->>Lambda: Return secret to warm-cache
    Lambda->>Lambda: Verify HMAC-SHA256 signature and timestamp
    Lambda->>DDB: Conditional put STRIPE_EVENT#event_id
    alt Duplicate event
        DDB-->>Lambda: Conditional check failed
        Lambda-->>APIGW: 200 already processed
        APIGW-->>Stripe: Acknowledged
    else New valid event
        DDB-->>Lambda: Idempotency lock acquired
        Lambda->>DDB: Upsert pass entitlement state
        Lambda->>Secrets: Fetch Apple/Google signing material
        Secrets-->>Lambda: Return signing material to warm-cache
        Lambda->>Lambda: Generate pass, signed manifest, and wallet JWT
        Lambda->>S3: Store temporary pass artifact with lifecycle expiry
        Lambda->>DDB: Persist pass_id, state, artifact reference, token metadata
        Lambda-->>APIGW: 200 accepted
        APIGW-->>Stripe: Acknowledged
        Member->>S3: Opens short-lived wallet delivery link
        S3-->>Member: Returns pass artifact
        Member->>Wallet: Adds Apple/Google Wallet pass
    end

    Merchant->>Wallet: Scans member wallet QR/barcode
    Wallet-->>Merchant: Presents signed wallet token
    Merchant->>Verify: POST /verify with wallet token and scan nonce
    Verify->>Secrets: Fetch verification key material if needed
    Verify->>Verify: Validate scanner auth, token signature, claims, expiry, entropy
    Verify->>DDB: Read current pass state
    Verify->>DDB: Conditional write scan nonce for replay detection
    alt Active, authentic, not replayed
        Verify-->>Merchant: accept with short decision TTL
    else Expired, revoked, invalid, or replayed
        Verify-->>Merchant: deny or review with reason code
    end
```
