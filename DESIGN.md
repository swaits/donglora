# Design Principles

These are the non-negotiable first principles of this project. Every design decision,
naming choice, module boundary, and abstraction is evaluated against them. When in
doubt, choose simplicity and clarity over cleverness.

## What This Is

A transparent LoRa radio over USB. Plug the dongle into your PC, talk to any LoRa
radio within range. That's it.

## What This Is Not

Not a mesh network node. Not a Meshtastic device. Not a protocol implementation. Not
an application framework. This firmware has no opinion about what you do with your
radio — it just gives you clean access to it.

## Principles

1. **Single purpose.** Transparent LoRa radio over USB. No mesh, no routing, no
   application logic. Ever.

2. **Protocol-agnostic.** The firmware is a dumb pipe. It exposes clean LoRa
   parameters (frequency, bandwidth, spreading factor, coding rate, sync word, TX
   power) and nothing else. No raw register access, no chip-specific leakage.

3. **Host-driven.** The firmware makes zero autonomous decisions. The radio idles on
   boot until the host commands it. No persistence across reboots. The host is always
   in control.

4. **Zero-config.** Boots, enumerates USB, waits for commands. The host plugs in and
   goes.

5. **Robustness over features.** Tasks never panic. Errors are reported to the host.
   The radio self-recovers. Ship fewer features, but make them bulletproof.

6. **Minimal footprint.** Avoid heavy dependencies. Keep the binary small. Every
   dependency must justify its inclusion.

7. **Auto-detect peripherals.** If the board has a display, keyboard, or sensors,
   use them. No user configuration required.

8. **World-class Rust.** Fully leverage the type system for safety. Strict `no_std`.
   Always clippy-clean. Thoughtfully designed — everything has an obvious home.
   Anyone who reads this code should immediately think *"this is nice."*

9. **Easy board support.** Adding a new board means dropping a `.rs` file and adding
   a Cargo feature. Nothing else changes.

10. **Support all common LoRa boards.** This project supports every common LoRa
    board, and even some uncommon ones. The architecture is designed to accommodate
    them cleanly. If the code isn't structured for a new board, fix the code.

11. **Minimal overhead.** The dongle should add as little latency as possible
    between the radio and the host. No unnecessary copies, no blocking operations
    in the radio path, no computation that isn't strictly needed.

12. **Standard toolchain.** No custom Rust forks or special SDKs. Use stock `rustup`
    channels (stable, nightly). Xtensa targets use nightly + `-Zbuild-std`; Cortex-M
    and RISC-V targets use stable. Boards that need the `esp` toolchain (via `espup`)
    are supported but gracefully skipped when the toolchain isn't installed.

## Architecture

```
Host PC
  │ USB CDC-ACM (COBS-framed fixed-size LE)
  ▼
usb_task ──Command──► radio_task ──► SX1262
         ◄──Response──     │
                      StatusWatch
                           ▼
                     display_task (optional) ──► OLED/TFT
```

Each task exclusively owns its peripheral. No shared state except typed channels and
a watch signal. Pure actor model.

## Peripheral Model

Boards can have optional peripherals beyond the radio and USB. The board's
`into_parts()` returns `Option<T>` slots for each, and the corresponding task is
only spawned when present.

| Peripheral | Slot | Task | Examples |
|---|---|---|---|
| Display | `Option<DisplayParts>` | `display_task` | SSD1306 OLED, ST7789 TFT |
| Input | `Option<InputParts>` | `input_task` | T-Deck keyboard, buttons |
| Telemetry | `Option<TelemetryParts>` | `telemetry_task` | Battery voltage, temperature |

**Board files are always separate.** A T-Deck is `t_deck.rs`, not a variant of
Heltec V3. Each board owns its own init code and pin mappings. Shared logic between
boards that use the same MCU can be factored into helper modules if it earns its
keep, but never prematurely.

## Technical Decisions

| Decision | Choice | Why |
|---|---|---|
| USB framing | COBS | Compact, `no_std`, zero-overhead frame delimiting |
| Serialization | Fixed-size LE | Every field at a known offset. No varints, no surprises |
| Async runtime | Embassy | De facto standard for async embedded Rust |
| Display | Radio status dashboard | Freq, BW, SF, packet counts, RSSI/SNR |
| Boot behavior | Idle until host commands | Host-driven principle |
| Persistence | None | Always start fresh, true dumb pipe |
| Board codegen | Jinja2 via build.rs | Auto-discovers boards from filesystem |
| Rust toolchain | Stock `rustup` (stable/nightly) | No forks; `espup` for Xtensa boards only |
| Firmware output | `firmware/donglora-{board}-{profile}.elf` | Readable names, not buried in `target/` |
