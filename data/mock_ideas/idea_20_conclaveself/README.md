# ConclaveSelf

Confidential survey aggregation in TEEs with public Solana attestation.
Survey designers (researchers, employers, governments) deploy a
ConclaveSelf instance — an Intel TDX enclave that ingests participant
responses encrypted in-browser and computes aggregate statistics
(averages, distributions, cross-tabs) only inside the enclave. The
designer sees aggregates; nobody sees raw responses, including the
platform.

The novelty over existing privacy-preserving survey tools (Pollfish,
Qualtrics with anonymization): ConclaveSelf publishes a TDX attestation
quote on Solana devnet at the end of the survey window. Anyone — funders,
ethics boards, the participants themselves — can verify the enclave ran
unmodified code and that no raw responses ever left the enclave.

Use cases: workplace pulse surveys (employees can answer honestly without
fear of retaliation), academic studies (IRB-friendly raw-data
non-collection), referendum-style civic input.

Stack: Phala CVM (TDX), FastAPI backend, browser-side AES-GCM encryption,
Solana devnet attestation publishing, Next.js operator dashboard.
