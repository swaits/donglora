set shell := ["bash", "-c"]

# Board definitions: feature target chip
# Xtensa targets use nightly cargo + esp rustc + -Zbuild-std=core.
# check-all gracefully skips boards whose toolchain isn't installed.
heltec_v3 := "heltec_v3 xtensa-esp32s3-none-elf esp32s3"
heltec_v4 := "heltec_v4 xtensa-esp32s3-none-elf esp32s3"
rak_wisblock_4631  := "rak_wisblock_4631 thumbv7em-none-eabihf nRF52840_xxAA"

firmware_dir := "firmware"

# All known boards
boards := "heltec_v3 heltec_v4 rak_wisblock_4631"

# Build release firmware for all boards with available toolchains
build-all:
    @trap 'exit 130' INT; \
    for board in {{boards}}; do \
        if just _can_build $board 2>/dev/null; then \
            echo "── building $board ──"; \
            just build $board || exit $?; \
        else \
            echo "── skipping $board (toolchain not available) ──"; \
        fi; \
    done

# Check all boards that can build with the available toolchain
check-all:
    @trap 'exit 130' INT; \
    for board in {{boards}}; do \
        if just _can_build $board 2>/dev/null; then \
            echo "── checking $board ──"; \
            just check $board || exit $?; \
        else \
            echo "── skipping $board (toolchain not available) ──"; \
        fi; \
    done

# Check a single board compiles
check board:
    @just _cargo {{board}} check

# Run clippy on a single board
clippy board:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    env=""; extra=""; \
    case "$target" in xtensa-*) \
        [ -f "$HOME/export-esp.sh" ] && . "$HOME/export-esp.sh"; \
        env="RUSTC=$(rustup which rustc --toolchain esp)"; extra="+nightly -Zbuild-std=core";; \
    esac; \
    eval $env cargo $extra clippy --target $target --features $feat -- -D warnings

# Build release firmware and copy to firmware/ with a readable name
build board profile="release":
    @just _cargo {{board}} "build --{{profile}}"
    @just _copy_firmware {{board}} {{profile}}

# Build and flash a board via probe-rs
flash board:
    @just build {{board}} release
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    probe-rs run --chip $chip "{{firmware_dir}}/lora-dongle-{{board}}-release.elf"

# Show binary size for a release build
size board:
    @just _cargo {{board}} "size --release"

# ── Private helpers ───────────────────────────────────────────────────

# Run a cargo command for a board.
# Xtensa: nightly cargo + esp rustc (via RUSTC override) + -Zbuild-std=core
[private]
_cargo board cmd:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    env=""; extra=""; \
    case "$target" in xtensa-*) \
        [ -f "$HOME/export-esp.sh" ] && . "$HOME/export-esp.sh"; \
        env="RUSTC=$(rustup which rustc --toolchain esp)"; extra="+nightly -Zbuild-std=core";; \
    esac; \
    eval $env cargo $extra {{cmd}} --target $target --features $feat

# Check if a board's toolchain is available
[private]
_can_build board:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    case "$target" in \
        xtensa-*) rustup toolchain list | grep -q "^esp" ;; \
        *) rustup target list --installed | grep -q "^$target$" || rustup target add "$target" >/dev/null 2>&1 ;; \
    esac

[private]
_copy_firmware board profile:
    @mkdir -p {{firmware_dir}}
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    src="target/$target/{{profile}}/lora-dongle"; \
    dst="{{firmware_dir}}/lora-dongle-{{board}}-{{profile}}"; \
    if [ -f "$src" ]; then cp "$src" "$dst.elf"; echo "→ $dst.elf"; fi

[private]
_info name:
    @if [ "{{name}}" == "heltec_v3" ]; then echo "{{heltec_v3}}"; \
     elif [ "{{name}}" == "heltec_v4" ]; then echo "{{heltec_v4}}"; \
     elif [ "{{name}}" == "rak_wisblock_4631" ]; then echo "{{rak_wisblock_4631}}"; \
     else echo "Unknown board: {{name}}" >&2; exit 1; fi
