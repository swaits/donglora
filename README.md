# DongLoRa

**/ˈdɒŋ.ɡəl.ɔːr.ə/** — a [portmanteau](https://en.wikipedia.org/wiki/Portmanteau) of **dongle** and **LoRa**.

Transparent LoRa radio over USB. Plug in a supported board, talk LoRa
from your host. The firmware is a dumb pipe — it exposes clean LoRa
parameters (frequency, bandwidth, spreading factor, coding rate, TX power)
and gets out of the way. No mesh logic, no protocol opinions, no config files.

## Quick Start

1. Get a [supported board](#supported-boards)
2. `just setup` (installs all tools and toolchains)
3. `just flash heltec_v4`
4. `just ex rx`
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

Python dependencies are handled automatically — just run:

```sh
just ex rx                     # receive packets
just ex tx                     # transmit a packet
just ex ping-pong --role tx    # two-dongle ping-pong demo
just ex test-commands          # exercise all DongLoRa commands
just ex bridge --mode server   # LoRa bridge over TCP
just ex meshcore               # MeshCore packet decoder
just ex run simple_rx          # run any example by name
```

| Script | Description |
|--------|-------------|
| [`simple_rx.py`](examples/simple_rx.py) | Configure radio, receive and print packets |
| [`simple_tx.py`](examples/simple_tx.py) | Transmit a single packet |
| [`ping_pong.py`](examples/ping_pong.py) | Two-dongle demo (`--role tx` / `--role rx`) |
| [`all_commands.py`](examples/all_commands.py) | Exercise all 8 commands (Ping, SetConfig, GetConfig, StartRx, StopRx, Transmit, DisplayOn/Off) |
| [`lora_bridge.py`](examples/lora_bridge.py) | Two-way LoRa bridge over TCP (works over Tailscale, WireGuard, etc.) |
| [`meshcore/`](examples/meshcore/) | Full MeshCore packet decoder (advanced example) |

## Building

Requires [just](https://github.com/casey/just), [mise](https://mise.jdx.dev/), and Rust.

```sh
just setup              # install all tools and toolchains (one-time)
just build-all          # build firmware for all boards
just build heltec_v4    # build a specific board
just check-all          # compile-check only (no firmware output)
just flash heltec_v4    # build + flash
just clippy heltec_v4   # lint
```

`just setup` handles everything: mise-managed tools (espup, espflash,
probe-rs), the ESP Xtensa toolchain, nightly rust-src, and ARM targets.
Individual build commands will also auto-install missing tools as needed.

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
