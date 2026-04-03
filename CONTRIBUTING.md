# Contributing to DongLoRa

## Adding Board Support

DongLoRa is designed to make adding new boards easy:

1. Create `firmware/src/board/your_board.rs` implementing the `init()` function
2. Add a Cargo feature in `firmware/Cargo.toml` with the board's dependencies
3. Add the board's feature/target/chip to the `justfile` boards list
4. `firmware/build.rs` auto-discovers the new file and generates the module selector

See existing board files (`heltec_v3.rs`, `rak_wisblock_4631.rs`) as templates.
Each board file owns all hardware init and returns peripheral bundles that the
common tasks consume. No shared board code — each board is self-contained.

## Code Style

- **Clippy-clean.** `just clippy <board>` must pass with no warnings.
- **No panics in tasks.** Use `match`/`if let`/`warn!` — never `.unwrap()` in async task code. Board init (runs once at startup) may use `.expect("reason")`.
- **Display rendering uses `.ok()`.** Drawing is best-effort; display errors are not recoverable.
- **Every `let _ =` gets an inline comment** explaining why the result is discarded.

## Client Libraries

Client libraries exist in [Python](clients/python/) and [Rust](clients/rust/).
To add a library in another language:

1. Create a directory with the language's standard project layout
2. Implement the wire protocol from [firmware/PROTOCOL.md](firmware/PROTOCOL.md)
3. Include device discovery (USB VID `1209`, PID `5741`)
4. Include COBS framing, command encoding, and response decoding
5. Add a mux client (connect to the mux daemon's Unix socket or TCP)

The protocol is intentionally simple — 8 commands, 7 responses, fixed-size LE.
A minimal client library should be implementable in a weekend.

## Building and Testing

```sh
cd firmware
just check-all      # Compile-check all boards
just build-all      # Build release firmware for all boards
just clippy <board> # Lint a specific board
just test           # Host-side protocol unit tests
```

Tool versions are pinned in each project's `mise.toml`.
Tools are installed automatically on first run.

## Commits

- [Conventional Commits](https://www.conventionalcommits.org/) format
- Logically grouped (one concern per commit)
- We use [jj](https://martinvonz.github.io/jj/) for version control
