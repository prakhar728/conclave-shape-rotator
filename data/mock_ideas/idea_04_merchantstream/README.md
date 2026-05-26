# MerchantStream

Shopify plugin that adds Solana checkout to any e-commerce store. A
shopper picks "Pay with Solana" at checkout; MerchantStream renders a QR
code and waits for the on-chain confirmation. Once confirmed, it calls the
Shopify Orders API to mark the order paid — the merchant ships from their
existing fulfillment flow without ever touching crypto.

Optional fiat off-ramp: if the merchant doesn't want to hold SOL or USDC,
MerchantStream auto-swaps to a stablecoin and bridges to a banking
partner's USD account once the daily volume crosses a threshold. The
merchant sees fiat in their bank by next business day.

We're piloting with two Shopify merchants doing $10k–$50k/mo in apparel
and digital art.

Stack: Shopify App (Node + Polaris), Solana web3.js, Jupiter, partner API
for off-ramp.
