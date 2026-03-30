# DongLoRa

Transparent LoRa radio over USB. Plug in a supported board, talk LoRa
from your host. The firmware is a dumb pipe — it exposes clean LoRa
parameters (frequency, bandwidth, spreading factor, coding rate, TX power)
and gets out of the way. No mesh logic, no protocol opinions, no config files.

## Quick Start

1. Get a [supported board](#supported-boards)
2. Install toolchain (see [Building](#building))
3. Build and flash: `just flash heltec_v4`
4. Run an example: `uv run examples/simple_rx.py`
5. See packets

## Supported Boards

| Board | MCU | Radio | Display |
|-------|-----|-------|---------|
| Heltec V3 | ESP32-S3 | SX1262 | SSD1306 OLED |
| Heltec V4 | ESP32-S3 | SX1262 | SSD1315 OLED |
| RAK WisBlock 4631 | nRF52840 | SX1262 | SSD1306 OLED (optional) |

## Protocol

DongLoRa speaks a binary protocol over USB CDC-ACM: COBS-framed,
fixed-size little-endian messages. 8 commands, 6 response types —
everything you need to configure the radio, transmit, and receive.

See **[docs/PROTOCOL.md](docs/PROTOCOL.md)** for the complete wire format
specification with worked examples.

## Examples

All examples use [uv](https://docs.astral.sh/uv/) for dependency management:

| Script | Description |
|--------|-------------|
| [`simple_rx.py`](examples/simple_rx.py) | Configure radio, receive and print packets |
| [`simple_tx.py`](examples/simple_tx.py) | Transmit a single packet |
| [`ping_pong.py`](examples/ping_pong.py) | Two-dongle demo (`--role tx` / `--role rx`) |
| [`meshcore/`](examples/meshcore/) | Full MeshCore packet decoder (advanced example) |

## Building

Requires [just](https://github.com/casey/just) and Rust.

```sh
just build-all          # build firmware for all boards (skips unavailable toolchains)
just build heltec_v4    # build a specific board
just check-all          # compile-check only (no firmware output)
just flash heltec_v4    # build + flash
just clippy heltec_v4   # lint
```

### Xtensa boards (Heltec V3/V4)

Requires the [ESP toolchain](https://github.com/esp-rs/espup):

```sh
cargo install espup
espup install --toolchain-version 1.82.0.3
```

### ARM boards (RAK 4631)

Stock Rust stable. Targets are installed automatically.

<details>
<summary><strong>Board Roadmap</strong></summary>

### Next Up

| Board | MCU | Radio |
|-------|-----|-------|
| Heltec V2 | ESP32 | SX1276 |
| Heltec Wireless Tracker | ESP32-S3 | SX1262 |
| Heltec Vision Master E213/E290 | ESP32-S3 | SX1262 |
| LilyGo T-Beam (SX1262) | ESP32 | SX1262 |
| LilyGo T-Beam Supreme | ESP32-S3 | SX1262 |
| LilyGo T-Echo | nRF52840 | SX1262 |
| LilyGo T3 S3 | ESP32-S3 | SX1262 |
| Seeed Studio Xiao nRF52 WIO | nRF52840 | SX1262 |

### Future

| Board | MCU | Radio |
|-------|-----|-------|
| Elecrow ThinkNode M1-M6 | various | various |
| Heltec Wireless Paper / MeshPocket / T114 | various | SX1262 |
| LilyGo T-Deck / T-Echo Lite / LoRa32 | various | various |
| RAK WisBlock 3112 / WisMesh variants | various | SX1262 |
| RPI Pico 2040 + WaveShare SX1262 | RP2040 | SX1262 |
| Seeed Studio SenseCAP / Xiao variants | various | SX1262 |

</details>

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) — Stephen Waits
