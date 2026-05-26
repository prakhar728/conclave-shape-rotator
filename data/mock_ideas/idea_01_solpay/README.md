# SolPay

A point-of-sale payment terminal for merchants accepting Solana. Built as a
React Native app that turns any Android tablet into a checkout device. The
merchant types an amount in their local currency; the app fetches the
SOL/fiat rate and renders a QR code. The customer scans with any Solana
wallet, signs the transaction, and the merchant sees a green checkmark
within ~400ms (Solana finality).

Funds settle directly to the merchant's wallet — no intermediary, no
custody. An optional "auto-swap to USDC" toggle uses Jupiter under the hood
to convert SOL receipts to a stablecoin in the same transaction.

We're targeting cafes, food trucks, and small retailers in Buenos Aires and
Lagos who already accept crypto informally but lack a clean checkout
surface. The pilot is with three coffee shops in BA.

Stack: React Native, Solana web3.js, Jupiter aggregator, Helius RPC.
