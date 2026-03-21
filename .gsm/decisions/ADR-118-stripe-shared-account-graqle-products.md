# ADR-118: Graqle Stripe Products on Shared CrawlQ Account

**Date:** 2026-03-21 | **Status:** ACCEPTED

## Context

Graqle needs Stripe billing for Pro ($19/mo) and Team ($29/dev/mo) plans.
Rather than creating a separate Stripe account, Graqle products are created
on the existing CrawlQ/Quantamix Stripe account (acct_1F8CQXFRtTTCtwHw).

This is a shared account that also hosts:
- CrawlQ TRACE products (Explorer, Professional, Business, Enterprise)
- FrictionMelt products (Essentials, Intelligence, Enterprise, Platform)
- Studio Intelligence products

## Decision

### Product Structure

Create 2 Graqle products with 4 prices (monthly + yearly for each):

| Product | Monthly | Yearly | Savings |
|---------|---------|--------|---------|
| Graqle Pro | $19/mo | $190/yr (save $38) | 17% |
| Graqle Team | $29/dev/mo | $290/dev/yr (save $58) | 17% |

### Naming Convention

All Graqle products prefixed with "Graqle" to distinguish from
CrawlQ/FrictionMelt products in the shared Stripe dashboard.

### Webhook

A single Stripe webhook endpoint handles all products:
- Endpoint: `https://graqle.com/api/stripe-webhook`
- Events: `checkout.session.completed`, `customer.subscription.updated`,
  `customer.subscription.deleted`
- The webhook handler maps Stripe price IDs to Cognito groups
  (`graqle-pro`, `graqle-team`)

### Security

- Stripe secret key is stored ONLY in Amplify environment variables
- NEVER committed to source code, ADRs, or documentation
- The publishable key (pk_live_*) is safe for client-side use
- Webhook signing secret stored in STRIPE_WEBHOOK_SECRET env var

### Environment Variables Required

```
STRIPE_SECRET_KEY=sk_live_***           # From Stripe dashboard
STRIPE_WEBHOOK_SECRET=whsec_***         # From webhook configuration
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_***  # Safe for client-side
STRIPE_PRICE_PRO_MONTHLY=price_***      # Created below
STRIPE_PRICE_PRO_YEARLY=price_***       # Created below
STRIPE_PRICE_TEAM_MONTHLY=price_***     # Created below
STRIPE_PRICE_TEAM_YEARLY=price_***      # Created below
```

## Consequences

**Positive:**
- No separate Stripe account to manage
- Shared billing dashboard for all Quantamix products
- Single payment method for customers who use multiple products

**Negative:**
- Must be careful to filter by product when viewing Stripe dashboard
- Webhook must route events to correct product (CrawlQ vs Graqle)
- Stripe account limits are shared across all products

**Risk Mitigation:**
- All Graqle products prefixed with "Graqle" for easy filtering
- Webhook checks price ID to determine which Cognito group to update
- Revenue can be tracked per product in Stripe dashboard
