# PrivBid

Sealed-bid NFT auctions with TEE-attested fairness. Bidders submit
encrypted bids during the auction window; bids are decrypted only inside
an Intel TDX enclave at the close of the auction. The enclave determines
the winner and second-highest bid (Vickrey auction), publishes the
result, and signs an attestation that the auction was conducted
according to the protocol.

The motivation: open-bid auctions on existing NFT marketplaces leak
information (snipers see all bids in real time, big bidders telegraph
their valuations). Sealed-bid Vickrey auctions are theoretically optimal
for revenue and truthful bidding but require a trusted auctioneer.
PrivBid replaces the trusted auctioneer with a TEE.

Built on Phala / Dstack (TDX); attestation hash published on Solana for
public verifiability. NFT settles directly from the seller's wallet to
the winner's at the disclosed second-highest price.

Stack: Anchor program, Phala CVM auction enclave, attestation
publication on Solana devnet, React frontend.
