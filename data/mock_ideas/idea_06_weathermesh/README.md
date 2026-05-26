# WeatherMesh

A community-run weather station network rewarded with SOL. Anyone with a
spare $80 can plug a WeatherMesh node into a Wi-Fi outlet on their roof or
balcony; the node uploads barometric pressure, temperature, humidity, and
wind data every five minutes. Each verified upload mints a small SOL
reward to the operator's wallet.

Data buyers — agriculture co-ops, insurance underwriters, hyperlocal
weather apps — pay per query. Revenue flows back to operators
proportional to the quality and uptime of their station.

The hardware is a Raspberry Pi Zero W with a $30 Bosch BME680 sensor and a
custom 3D-printed enclosure (STL files in the repo). Firmware signs each
reading with the device's keypair before upload, and the on-chain program
verifies the signature before issuing the reward.

Stack: Anchor program, ESP32 firmware (Rust), Next.js operator dashboard,
The Graph for data indexing.
