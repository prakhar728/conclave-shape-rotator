# RoyaltySplit

Programmable on-chain music royalty splits. A musician releases a track
as an SPL token; collaborators (producer, featured artists, sample
clearance) are encoded as royalty recipients with percentages. Every
streaming payout, sync license fee, or NFT secondary sale flows through
the split contract and lands in each contributor's wallet automatically
— no label, no manager, no wire transfers.

The novel piece: splits are *modifiable* by quorum of recipients. If a
new contributor is added (e.g., a remixer), the existing recipients vote
to admit them and dilute their own percentages accordingly. Disputes are
resolved by a multisig of the original artists.

Pilot users: three indie electronic producers we've been working with who
currently track splits in shared Google Sheets and pay via Wise.

Stack: Anchor program for splits + voting, Next.js dashboard, integration
with on-chain music platforms (Audius, Sound.xyz).
