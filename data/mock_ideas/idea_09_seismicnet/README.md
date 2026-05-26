# SeismicNet

A distributed earthquake sensor network running on Solana. Anyone in a
seismically active region can host a SeismicNet node — a low-cost
geophone connected to a Raspberry Pi — and earn SEIS tokens for every
verified ground-motion reading uploaded.

The science angle: dense, low-cost sensor networks can detect P-waves
seconds before destructive S-waves arrive at population centers, enabling
early-warning systems that save lives. Existing networks (USGS, JMA) are
sparse and government-funded; we want a community-funded layer that
fills the gaps.

When a quake is detected, nodes broadcast to a Solana program; the
program correlates readings across geographically-distributed nodes to
confirm the event. Confirmed events trigger early-warning push
notifications to subscribed apps within ~3 seconds.

Stack: Anchor program with custom event-correlation logic, Raspberry Pi
firmware in C, geophone hardware spec in repo, React subscriber app for
push notifications.
