# Contributing to DongLoRa

## Adding Board Support

DongLoRa is designed to make adding new boards easy:

1. Create `src/board/your_board.rs` implementing the `init()` function
2. Add a Cargo feature in `Cargo.toml` with the board's dependencies
3. Add the board's feature/target/chip to the `justfile` boards list
4. `build.rs` auto-discovers the new file and generates the module selector

See existing board files (`heltec_v3.rs`, `rak_wisblock_4631.rs`) as templates.
Each board file owns all hardware init and returns peripheral bundles that the
common tasks consume. No shared board code — each board is self-contained.

## Code Style

- **Clippy-clean.** `just clippy <board>` must pass with no warnings.
- **No panics in tasks.** Use `match`/`if let`/`warn!` — never `.unwrap()` in async task code. Board init (runs once at startup) may use `.expect("reason")`.
- **Display rendering uses `.ok()`.** Drawing is best-effort; display errors are not recoverable.
- **Every `let _ =` gets an inline comment** explaining why the result is discarded.

## Building and Testing

```sh
just setup         # Install all tools and toolchains (one-time)
just check-all     # Compile-check all boards
just build-all     # Build release firmware for all boards
just clippy <board> # Lint a specific board
```

Tool versions (espup, espflash, probe-rs) are pinned in `mise.toml`.
`just setup` installs everything; individual commands also auto-install as needed.

## Commits

- [Conventional Commits](https://www.conventionalcommits.org/) format
- Logically grouped (one concern per commit)
- We use [jj](https://martinvonz.github.io/jj/) for version control
