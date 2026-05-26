# DecayVote

A time-decay quadratic voting program for Solana DAOs. Voting power
decays exponentially the longer a token holder has been inactive — if you
haven't voted in three months, your voting weight halves. Active
participants accumulate weight; passive holders lose it.

The mechanism: every governance epoch, each token holder's effective
weight is recomputed as `weight = sqrt(tokens) * exp(-lambda * t)` where
`t` is days since last vote and `lambda` is set per-DAO. Voting in any
proposal resets `t` to zero.

The thesis: governance attacks (whale capture, vote-mining) work because
inactive holders' weight is recoverable. Time-decay makes ambient voting
power expire, forcing engagement.

Targeting Solana DAOs frustrated with low quorum and whale dominance —
Realms, Squads, MarinadeDAO are early conversations.

Stack: Anchor governance program with epoch-based weight recomputation,
Realms-compatible UI, off-chain indexer for vote-decay queries.
