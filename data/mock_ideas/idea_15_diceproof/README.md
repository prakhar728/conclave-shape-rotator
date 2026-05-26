# DiceProof

A verifiable randomness oracle for tabletop game apps on Solana. When a
game app needs a die roll, card draw, or loot drop, it requests a random
value from DiceProof. The oracle generates the value using a VRF
(verifiable random function), commits the proof on-chain, and returns
the value to the app.

Anyone can verify that the value was not chosen by the oracle, the app
developer, or the player — the VRF proof guarantees the output is
deterministically derived from the request and the oracle's secret key,
which the oracle can't influence after the fact.

Why this matters: dozens of on-chain card games and roguelikes have
shipped with insecure RNG (Math.random, blockhash) and been
trivially exploited. DiceProof gives game devs a drop-in oracle that
makes their RNG provably fair.

Stack: Anchor program with VRF verification, Switchboard-compatible
oracle node, JavaScript SDK for game devs, React demo game.
