# DongLoRa

Transparent LoRa radio over USB. Plug in a board, talk LoRa from your host.

## Supported Boards

| Board | Status | MCU | Radio |
|---|---|---|---|
| Heltec v3 | builds | ESP32-S3 | SX1262 |
| Heltec v4 | builds | ESP32-S3 | SX1262 |
| RAK WisBlock / WisMesh (RAK 4631) | **firmware** | nRF52840 | SX1262 |

## Next Up

High-priority boards — popular, well-documented, should be straightforward:

| Board | MCU | Radio | Notes |
|---|---|---|---|
| Heltec v2 | ESP32 | SX1276 | Xtensa, older radio |
| Heltec Wireless Tracker (v1/v2) | ESP32-S3 | SX1262 | GPS + display |
| Heltec Vision Master E213 / E290 | ESP32-S3 | SX1262 | E-ink display |
| LilyGo T-Beam (SX1262) | ESP32 | SX1262 | GPS, popular |
| LilyGo T-Beam Supreme (SX1262) | ESP32-S3 | SX1262 | GPS, newer |
| LilyGo T-Echo | nRF52840 | SX1262 | E-ink, BLE |
| LilyGo T3 S3 (SX126x) | ESP32-S3 | SX1262 | Common dev board |
| RAK WisBlock 3112 | ? | SX1262 | RAK ecosystem |
| RAK WisMesh 1W Booster (3401 + 13302) | ? | SX1262 | High power |
| RAK WisMesh Tag | ? | SX1262 | Small form factor |
| Seeed Studio Xiao nRF52 WIO | nRF52840 | SX1262 | Tiny |
| Seeed Studio SenseCAP T1000-E | ? | SX1262 | Tracker |

## Future

Lower priority or niche — contributions welcome:

| Board | MCU | Radio |
|---|---|---|
| Elecrow ThinkNode M1 / M2 / M3 / M5 / M6 | various | various |
| GAT-IoT GAT562 30s / Tracker | ? | ? |
| Heltec Heltec Wireless Paper | ESP32-S3 | SX1262 |
| Heltec MeshPocket | ESP32-S3 | SX1262 |
| Heltec MeshSolar / MeshTower | ESP32-S3 | SX1262 |
| Heltec T114 | nRF52840 | SX1262 |
| Heltec WSL3 | ? | ? |
| Ikoka Nano / Stick | ? | ? |
| Keepteen LT1 | ? | ? |
| LilyGo T-Beam 1.2 (SX1276) | ESP32 | SX1276 |
| LilyGo T-Deck (community) | ESP32-S3 | SX1262 |
| LilyGo T-Echo Lite | nRF52840 | SX1262 |
| LilyGo T3 S3 (SX127x) | ESP32-S3 | SX1276 |
| LilyGo LoRa32 V2.1.1.6 | ESP32 | SX1276 |
| ProMicro nRF52 (faketec) | nRF52840 | SX1262 |
| RPI Pico 2040 + WaveShare SX1262 | RP2040 | SX1262 |
| Seeed Studio SenseCAP Solar | ? | SX1262 |
| Seeed Studio Wio Tracker L1 EINK / Pro | ? | SX1262 |
| Seeed Studio Xiao C3 | ESP32-C3 | SX1262 |
| Seeed Studio Xiao S3 WIO | ESP32-S3 | SX1262 |
| UnitEng Nano G2 Ultra / Station G2 | ? | ? |

## Building

```sh
just build-all          # build firmware for all boards with available toolchains
just build heltec_v4    # build a specific board
just check-all          # compile-check all boards (no firmware output)
just flash heltec_v4    # build + flash via probe-rs
```

### Xtensa (ESP32) boards

Requires the [esp toolchain](https://github.com/esp-rs/espup):

```sh
cargo install espup
espup install --toolchain-version 1.82.0.3
```

### ARM (nRF, STM32) boards

Stock Rust stable. Targets are installed automatically.
