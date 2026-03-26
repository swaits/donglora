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

7. **Auto-detect peripherals.** If the board has a display, use it. No user
   configuration required.

8. **World-class Rust.** Fully leverage the type system for safety. Strict `no_std`.
   Always clippy-clean. Thoughtfully designed — everything has an obvious home.
   Anyone who reads this code should immediately think *"this is nice."*

9. **Easy board support.** Adding a new board means dropping a `.rs` file and adding
   a Cargo feature. Nothing else changes.

## Architecture

```
Host PC
  │ USB CDC-ACM (COBS-framed postcard)
  ▼
usb_task ──Command──► radio_task ──► SX1262
         ◄──Response──     │
                      StatusWatch
                           ▼
                     display_task (optional) ──► OLED/TFT
```

Each task exclusively owns its peripheral. No shared state except typed channels and
a watch signal. Pure actor model.

## Technical Decisions

| Decision | Choice | Why |
|---|---|---|
| USB framing | COBS + postcard | Compact, `no_std` native, battle-tested |
| Serialization | postcard + serde | Zero-alloc binary codec, perfect for embedded |
| Async runtime | Embassy | De facto standard for async embedded Rust |
| Display | Radio status dashboard | Freq, BW, SF, packet counts, RSSI/SNR |
| Boot behavior | Idle until host commands | Host-driven principle |
| Persistence | None | Always start fresh, true dumb pipe |
| Board codegen | Jinja2 via build.rs | Auto-discovers boards from filesystem |
