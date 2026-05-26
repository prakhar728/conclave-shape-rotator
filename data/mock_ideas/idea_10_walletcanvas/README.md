# WalletCanvas

A visual portfolio dashboard that lives inside a Solana wallet as a
plugin. Instead of a flat list of token balances, WalletCanvas renders
the user's holdings as an interactive treemap — area proportional to USD
value, color by 24h price change, click for transaction history.

The novel piece: WalletCanvas tracks the *origin* of each holding (mint,
swap, airdrop, NFT royalty) and lets the user filter by source. "Show
me only what I bought" hides airdropped junk; "show me what I earned"
surfaces NFT royalties and staking rewards.

Targeted at active Solana users who hold 50+ tokens and want a clean
mental model of their portfolio without leaving the wallet.

Stack: Phantom + Backpack plugin SDK, D3 for the treemap, Helius RPC for
transaction history, local SQLite cache for performance, React + Tailwind
for the UI.
