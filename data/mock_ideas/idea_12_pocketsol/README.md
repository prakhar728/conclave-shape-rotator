# PocketSol

A kid-friendly Solana wallet with parental controls. Parents fund their
kid's PocketSol wallet with a weekly allowance; the kid can spend within
limits the parent sets — daily caps, allowed merchants, NFT-only spending,
no NFT spending.

The control layer is a Solana program that wraps the kid's wallet: every
outbound transaction goes through a permission check. Approvals happen on
the kid's side instantly when within policy, or get queued for parental
approval if outside policy.

Built-in features: chore-based earnings (parent marks a chore complete →
kid earns SOL), savings goals with visual progress, and a parent dashboard
showing every transaction.

We're targeting parents who want their kids to learn money management
with crypto-native primitives without giving them unlimited
self-custody.

Stack: Anchor program for permissioned spending, React Native for the kid
app, Next.js for the parent dashboard, Privy for parent identity.
