# FlowPayments

B2B invoice settlement on Solana with built-in net-30 / net-60 terms. A
buyer receives an invoice, signs an approval transaction, and the program
automatically releases payment to the seller on the due date — no manual
follow-up, no missed payments. If the buyer wants to cancel before the due
date, they can; if they want to pay early for a discount, the program
applies the discount automatically.

Targets the long tail of small B2B relationships where Stripe Invoice and
Plaid are overkill but a wire transfer is too slow. Think: design agencies
billing $5k clients, freelance dev shops invoicing startups, contract
manufacturers settling materials orders.

Stack: Anchor program (escrow + scheduled release), Next.js dashboard for
buyers and sellers, Helius webhooks for invoice notifications, optional
USDC settlement via Jupiter.
