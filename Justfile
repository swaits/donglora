set shell := ["bash", "-c"]
heltec_v3 := "heltec_v3 xtensa-esp32s3-none-elf esp32s3"
rak_4631  := "rak_4631 thumbv7em-none-eabihf nRF52840_xxAA"

# Check all boards compile cleanly
check-all:
    just check heltec_v3
    just check rak_4631

# Check a single board compiles
check board:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    cargo check --target $target --features $feat

# Run clippy on a single board
clippy board:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    cargo clippy --target $target --features $feat -- -D warnings

# Build and flash a board via probe-rs
flash board:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    cargo build --release --target $target --features $feat; \
    probe-rs run --chip $chip --target $target --features $feat

# Show binary size for a release build
size board:
    @read -r feat target chip <<< "$(just _info {{board}})"; \
    cargo size --release --target $target --features $feat

[private]
_info name:
    @if [ "{{name}}" == "heltec_v3" ]; then echo "{{heltec_v3}}"; \
     elif [ "{{name}}" == "rak_4631" ]; then echo "{{rak_4631}}"; \
     else echo "Unknown board" >&2; exit 1; fi
