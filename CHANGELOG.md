# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added

- Transparent LoRa radio over USB CDC-ACM (VID `1209`, PID `5741`)
- COBS-framed fixed-size LE binary protocol (8 commands, 6 responses)
- Radio configuration: frequency, bandwidth, spreading factor, coding rate, TX power
- Continuous RX mode with RSSI/SNR per packet
- Single-shot TX with optional per-packet config override
- SSD1306 OLED display support with status dashboard
  - Radio state, frequency, modulation parameters
  - Packet counters (RX/TX)
  - RSSI sparkline (1-minute history, TX shown as dotted bars)
  - Combined splash/waiting screen on disconnect
- Auto-detect USB host connect/disconnect via DTR
- Config validation against per-board hardware limits
- `TX_POWER_MAX` sentinel (`-128`): auto-use the board's maximum TX power
- Board support: Heltec V3, Heltec V4, RAK WisBlock 4631
- Example: MeshCore packet decoder with group channel decryption

### Technical

- Embassy async runtime (no threads, CPU sleeps when idle)
- Zero-config: boots and waits for host commands
- Protocol-agnostic: firmware has no opinion about what you transmit
- Tasks never panic: all errors reported to host or logged
- Board abstraction: one `.rs` file + one Cargo feature per board
