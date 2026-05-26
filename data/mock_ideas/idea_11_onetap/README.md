# OneTap

A passkey-based Solana wallet for first-time crypto users. No seed
phrase. No browser extension. The user signs up with their Apple ID or
Google account; the wallet uses WebAuthn / passkeys to derive a Solana
keypair on the device's secure enclave. Authentication is a Face ID tap.

For recovery, the user adds a second device (also passkey-secured); a
2-of-3 social recovery scheme uses Shamir secret sharing across the
user's devices and a recovery contact's device. No service holds the
key, including OneTap.

The bet: 95% of would-be Solana users bounce when they see "write down
these 12 words." Removing the seed phrase removes the entire onboarding
cliff.

Stack: React Native, WebAuthn for passkey, Solana web3.js, custom Anchor
program for on-chain social recovery, secure-enclave key storage.
