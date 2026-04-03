# DongLoRa

**/ˈdɒŋ.ɡəl.ɔːr.ə/** — a [portmanteau](https://en.wikipedia.org/wiki/Portmanteau) of **dongle** and **LoRa**.

Transparent LoRa radio over USB. Plug in a supported board, talk LoRa
from your host in any language that can open a serial port.

The firmware is a dumb pipe — it exposes clean LoRa parameters (frequency,
bandwidth, spreading factor, coding rate, TX power) and gets out of the way.
No mesh logic, no protocol opinions, no config files.

## How It Works

```
Your code ──► USB serial ──► firmware ──► LoRa radio

Your code ──► client library ──► USB serial ──► firmware ──► LoRa radio

Your code ──► client library ──┐
Your code ──► client library ──┤
              ...              ├──► mux daemon ──► USB serial ──► firmware ──► LoRa radio
Your code ──► client library ──┤
Your code ──► client library ──┘
```

Four components, each self-contained with its own dependencies and tooling:

| Component | What it is | Language |
|-----------|-----------|----------|
| **[firmware/](firmware/)** | Embedded firmware flashed onto a LoRa board. Speaks a simple [binary protocol](firmware/PROTOCOL.md) over USB. | Rust |
| **[clients/](clients/)** | Client libraries that handle device discovery, COBS framing, and protocol encoding/decoding. This is what your code imports. | Python (reference) |
| **[mux/](mux/)** | Optional daemon that lets multiple applications share one dongle. Owns the USB port, exposes a Unix socket (and optional TCP). | Python |
| **[examples/](examples/)** | Ready-to-run scripts demonstrating the client library — receive, transmit, bridge, MeshCore decoder, AI bot. | Python |

The client library can talk directly to the firmware over USB, or connect
through the mux when multiple applications need the same dongle.

## Quick Start

1. Get a [supported board](#supported-boards)
2. `cd firmware && just flash heltec_v4`
3. `cd examples && just rx`
4. See packets

## Supported Boards

| Board | MCU | Radio | Display |
|-------|-----|-------|---------|
| Heltec V3 | ESP32-S3 | SX1262 | SSD1306 OLED |
| Heltec V4 | ESP32-S3 | SX1262 | SSD1315 OLED |
| RAK WisBlock 4631 | nRF52840 | SX1262 | SSD1306 OLED (optional) |

## Examples

Dependencies are handled automatically:

```sh
cd examples
just rx                     # receive packets
just tx                     # transmit a packet
just ping-pong --role tx    # two-dongle ping-pong demo
just test-commands          # exercise all DongLoRa commands
just bridge --mode server   # LoRa bridge over TCP
just meshcore               # MeshCore packet decoder
just orac                   # MeshCore AI bot (needs ANTHROPIC_API_KEY)
just telemetry              # MeshCore repeater telemetry monitor
```

## Multiplexer

To share one dongle across multiple applications, run the mux daemon:

```sh
cd mux/python
just run                                    # start the mux daemon
just verbose                                # start with verbose logging
just run --tcp 5741 --port /dev/ttyACM0     # with explicit options
```

The mux owns the USB serial port exclusively and exposes a Unix socket
(and optional TCP) speaking the same protocol. Client libraries connect
through it transparently.

| Script | Description |
|--------|-------------|
| [`simple_rx.py`](examples/simple_rx.py) | Configure radio, receive and print packets |
| [`simple_tx.py`](examples/simple_tx.py) | Transmit a single packet |
| [`ping_pong.py`](examples/ping_pong.py) | Two-dongle demo (`--role tx` / `--role rx`) |
| [`all_commands.py`](examples/all_commands.py) | Exercise all 9 commands |
| [`lora_bridge.py`](examples/lora_bridge.py) | Two-way LoRa bridge over TCP (works over Tailscale, WireGuard, etc.) |
| [`meshcore/`](examples/meshcore/) | Full MeshCore packet decoder, AI bot, telemetry monitor |

## Device Permissions (Linux)

Your user needs read/write access to the serial device (`/dev/ttyACM*` or
`/dev/ttyUSB*`). The cleanest fix is a udev rule:

```sh
# /etc/udev/rules.d/99-donglora.rules
SUBSYSTEM=="tty", ATTRS{idVendor}=="1209", ATTRS{idProduct}=="5741", MODE="0666"
```

Then reload:

```sh
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Without this, you'll get permission errors when opening the serial port.

## Building

Requires [just](https://github.com/casey/just) and [mise](https://mise.jdx.dev/).
Everything else is installed automatically on first run.

```sh
cd firmware
just build heltec_v4    # build a specific board
just build-all          # build firmware for all boards
just flash heltec_v4    # build + flash
just check-all          # compile-check only
just clippy heltec_v4   # lint
just test               # host-side protocol unit tests
```

## Roadmap

### Now: Solidify the Foundation

- [ ] Test on more boards (Heltec V2, T-Beam Supreme, T-Echo, RAK 3112)
- [ ] Python client library on PyPI — the existing library, properly packaged
- [ ] CI for all boards — automated build/clippy/size-check on every commit
- [ ] Protocol documentation polish

### Next: Cross-Language Client Libraries

The protocol is 8 commands over COBS-framed LE. Any language that can
open a serial port can speak DongLoRa.

- [ ] **Rust** crate — async, tokio-native, zero-copy COBS
- [ ] **Go** module — goroutine-friendly, cross-platform
- [ ] **C** library — `libdonglora` for FFI from any language
- [ ] **Ruby** gem — simple protocol, weekend gem, new community
- [ ] **Python** on PyPI — type hints and async support

### Then: Infrastructure and Tooling

- [ ] Cross-platform mux daemon rewritten in Rust (single static binary, no Python required)
- [ ] `donglora-ctl` CLI — ping, configure, receive, transmit, scan frequencies. Think `ip link` for LoRa.
- [ ] Protocol versioning — version handshake so client libraries can detect firmware capabilities
- [ ] Firmware OTA over USB — field-upgradeable without a flash tool

### Future: Things That Would Be Amazing

All host-driven, firmware stays dumb. Every item passes the pipe test.

- [ ] **Spectrum analyzer** — host sweeps frequencies, radio reports RSSI at each step. Instant RF site survey tool.
- [ ] **Multi-dongle coordination** — one host, multiple dongles on different frequencies. Frequency-hopping, parallel monitoring, diversity reception — all host-driven.
- [ ] **LoRa packet capture** — PCAP-NG with a LoRa link type. Wireshark dissectors. Record, replay, analyze LoRa traffic with standard tools.
- [ ] **Time-synchronized RX** — "start RX at T, stop at T+N" for precise duty-cycle control and TDMA-style protocols. Firmware just follows the schedule.
- [ ] **Raw IQ streaming** — SDR-lite for LoRa. Demodulation and signal analysis on the host.
- [ ] **Mesh protocol test harness** — host-side framework for testing any mesh protocol over real radios. Inject packets, measure latency, simulate topology. The dongle is just the radio — test logic lives entirely on the host.

*Have an idea? Open an issue. The protocol is stable and the firmware is
intentionally boring — the interesting stuff happens on the host.*

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
