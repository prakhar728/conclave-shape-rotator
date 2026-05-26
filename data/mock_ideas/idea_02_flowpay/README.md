# FlowPay

Per-second streaming payments on Solana. Subscriptions, payroll, and
freelance retainers paid as a continuous flow rather than a monthly lump
sum. A subscriber locks 30 days of SOL or USDC into a stream contract; the
recipient can withdraw the streamed-so-far amount at any time. Either side
can cancel — the unstreamed remainder returns to the sender.

The killer use case is SaaS subscriptions: instead of paying a $20/mo
charge upfront, the user streams $0.66/day and stops the stream the moment
they cancel. No refund logic, no chargebacks.

We modeled the program after Sablier and Superfluid (both EVM-only) but
rewrote it in Anchor for Solana's account model. Streams use a PDA per
sender-recipient pair; the read path is a single getAccountInfo call.

Stack: Anchor (Rust), Solana web3.js, React frontend, optional Jupiter
auto-swap to USDC at stream creation.
