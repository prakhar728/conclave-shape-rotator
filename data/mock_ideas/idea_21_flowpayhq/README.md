# FlowPayHQ

Recurring B2B payments on Solana for SaaS vendors. A vendor onboards their
customers once; FlowPayHQ generates a permissioned spend authority on the
customer's wallet that auto-debits the agreed monthly amount on the due
date. The customer can revoke at any time; the vendor never holds funds
between charges.

The differentiator versus existing recurring-payment programs: FlowPayHQ
treats *failed* charges as first-class — when a customer's wallet doesn't
have sufficient balance on the due date, FlowPayHQ retries with
exponential backoff and emits a webhook the vendor can route to dunning
flows (email, in-app banner, downgrade-to-free). Today this requires
custom indexer code per vendor.

We're targeting Solana-native SaaS tools (RPC providers, indexer APIs,
dev-tooling subscriptions) currently using Stripe + manual offramp.
Pilots: two RPC providers and one indexing platform have signed LOIs.

Stack: Anchor program (delegated spend authority + retry queue), Helius
webhooks for charge notifications, Next.js vendor dashboard, TypeScript
SDK for vendor integration.
