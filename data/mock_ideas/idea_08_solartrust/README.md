# SolarTrust

Rooftop solar telemetry as a verifiable on-chain feed. Homeowners and
small commercial solar installations plug a SolarTrust device into their
inverter's monitoring port; the device reads kilowatt-hour generation in
real time and posts signed proofs to Solana every 15 minutes.

The use case: renewable energy credits (RECs) and carbon offset markets
currently rely on self-reported or poorly-audited generation data.
SolarTrust gives buyers a cryptographic guarantee that each REC
corresponds to actual measured generation from a known device.

Operators (the homeowner / solar installer) get paid in SOLAR tokens for
each verified kWh. RECs are minted as SPL tokens with the device ID,
generation timestamp, and signed reading as metadata. Buyers can verify
end-to-end on-chain.

Stack: Anchor program, ESP32 firmware reading Modbus from inverters, Rust
crypto for signing, Next.js operator dashboard, SPL token program for
REC issuance.
