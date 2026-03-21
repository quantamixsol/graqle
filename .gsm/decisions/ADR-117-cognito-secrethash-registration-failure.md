# ADR-117: Cognito SecretHash Registration Failure — Root Cause & Prevention

**Date:** 2026-03-21 | **Status:** ACCEPTED | **Severity:** P0 (User-facing registration broken)

## Context

User `116564@amstelveencollege.nl` attempted to register on graqle.com Studio and received "Registration failed" with no useful error message. Investigation revealed registration was broken for ALL new users, not just this one.

## Root Cause

**Missing environment variable: `GRAQLE_BACKEND_CLIENT_SECRET`**

The Cognito User Pool has two app clients:
1. **Frontend client** (`pkjrj7va3qu06sk9onmdqef3m`) — NO secret, used by Amplify JS SDK for browser login
2. **Backend client** (`42a1nn48g7ao5ntkesedrbns7a`) — WITH secret, used by Next.js API routes for registration

The backend client requires `SecretHash = Base64(HMAC-SHA256(email + clientId, clientSecret))` on every Cognito API call (SignUp, ConfirmSignUp, ResendCode). When `GRAQLE_BACKEND_CLIENT_SECRET` is not set in Amplify environment variables:

1. `CLIENT_SECRET` defaults to `""` (empty string)
2. `SecretHash` becomes `undefined` (line 60: `CLIENT_SECRET ? getSecretHash(...) : undefined`)
3. Cognito rejects the SignUp with a generic error
4. Error falls into catch-all: `"Registration failed. Please try again."` (HTTP 500)
5. User sees no actionable error message

## Why It Wasn't Detected Earlier

1. **Silent failure** — The generic catch-all error masked the root cause
2. **Local dev works** — `.env.local` had the secret; Amplify did not
3. **No startup validation** — The app never checked if `CLIENT_SECRET` was present
4. **No monitoring** — No alert for 500 errors on `/api/auth/register`

## Secondary Incident: Amplify Env Var Wipe

During the fix, `aws amplify update-app --environment-variables` was used to add the missing secret. **This command REPLACES the entire env var map.** All 12 existing env vars (S3 credentials, Stripe keys, Cognito pool IDs) were wiped. They had to be restored manually, and a new S3 access key had to be generated.

## Decision

### Immediate Fix
1. Added `GRAQLE_BACKEND_CLIENT_SECRET` to Amplify env vars
2. Restored all 12 env vars after the wipe incident
3. Improved error handling: catch `NotAuthorizedException`, `ResourceNotFoundException` with CRITICAL log messages
4. Added production warning log if `CLIENT_SECRET` is empty

### Prevention Rules

| Rule | Implementation |
|------|---------------|
| **Never use `aws amplify update-app --environment-variables` for single var** | Always read current vars first, merge, then update |
| **All auth env vars must be validated at build time** | Added warning log for missing `CLIENT_SECRET` |
| **Catch-all errors must log the error type** | Changed error handler to include `errorName` in server logs |
| **Registration errors must be actionable** | Generic errors now include error type hint in message |
| **Test registration after every Amplify deploy** | Add to deployment checklist |

### Required Amplify Env Vars (Complete Set)

```
# Auth (CRITICAL — registration breaks without these)
GRAQLE_BACKEND_CLIENT_ID=42a1nn48g7ao5ntkesedrbns7a
GRAQLE_BACKEND_CLIENT_SECRET=<from Cognito>
GRAQLE_USER_POOL_ID=eu-central-1_RwEo6O1ow
NEXT_PUBLIC_GRAQLE_USER_POOL_CLIENT_ID=pkjrj7va3qu06sk9onmdqef3m
NEXT_PUBLIC_GRAQLE_USER_POOL_ID=eu-central-1_RwEo6O1ow

# S3 (graph storage — graph loading breaks without these)
GRAQLE_S3_ACCESS_KEY_ID=<from IAM>
GRAQLE_S3_SECRET_ACCESS_KEY=<from IAM>

# Lambda (optional — fallback for reasoning/graph)
NEXT_PUBLIC_LAMBDA_URL=https://r3tj3qkjfu6ecxtpw7cb57jbha0qjmaw.lambda-url.eu-central-1.on.aws

# Stripe (payments — billing page breaks without these)
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_PRO_YEARLY=price_...
STRIPE_PRICE_TEAM_MONTHLY=price_...
STRIPE_PRICE_TEAM_YEARLY=price_...
```

## Consequences

**Positive:**
- Registration now works for all users
- Future SecretHash failures will be caught with specific error messages
- KG lesson node `lesson_20260321T100102` will surface this pattern in preflight checks
- ADR documents the complete env var set for Amplify

**Negative:**
- S3 access key had to be rotated (old key `REDACTED_KEY` deleted)
- Stripe secret key and webhook secret were lost and need re-entry from Stripe dashboard
- Window of ~15 minutes where all env vars were missing (between wipe and restore)

## Files Changed
- `src/app/api/auth/register/route.ts` — Improved error handling, startup validation
- Amplify environment variables — Added `GRAQLE_BACKEND_CLIENT_SECRET`
