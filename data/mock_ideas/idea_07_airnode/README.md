# AirNode

A token-incentivized air quality sensor network. Every AirNode device
measures PM2.5, PM10, NO2, ozone, and CO2 every minute and uploads
signed readings to a Solana program. Operators earn AIR tokens
proportional to uptime and data quality (cross-validated against
neighboring nodes).

Cities, environmental NGOs, and academic researchers can query the live
sensor map for a fee. We index against EPA monitoring stations to detect
faulty or spoofed nodes and slash their rewards.

We're starting in Delhi and Jakarta, where official monitoring is sparse
and air quality is consistently the worst public health input. Operators
get a node for $120 (subsidized in the pilot); the unit pays back in
roughly 6 months at current AIR token rates.

Stack: Anchor program, Sensirion SPS30 + SCD41 sensors on an ESP32, Rust
firmware, React dashboard with Mapbox heatmap, Pyth-style staking for
data validators.
