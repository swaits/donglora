# donglora-cobs

Minimal COBS (Consistent Overhead Byte Stuffing) encoder/decoder.

- `no_std`, zero-alloc, zero dependencies at runtime
- Spec-compliant: implements Cheshire & Baker (IEEE/ACM 1999)
- Exhaustively tested: 39 tests including cross-validation against `corncobs`

## Why our own crate?

DongLoRa is an embedded firmware project. We want:
- Zero runtime dependencies (just 130 lines of code)
- Complete control over the implementation
- Spec compliance verified against both the canonical Wikipedia vectors
  AND a battle-tested third-party crate (`corncobs`)

For higher-throughput use cases, consider
[corncobs](https://crates.io/crates/corncobs) which has been
benchmark-optimized for streaming applications.

## Testing

```sh
# Unit tests + property tests + interop
cargo test -p donglora-cobs

# Fuzz testing (requires cargo-fuzz: cargo install cargo-fuzz)
cd crates/donglora-cobs
cargo +nightly fuzz run fuzz_decode -- -max_total_time=60
cargo +nightly fuzz run fuzz_roundtrip -- -max_total_time=60
```

Tests include:
- 18 canonical COBS vectors (Wikipedia / IEEE/ACM spec)
- Round-trip verification for various payload sizes
- 8 interop tests cross-validating against `corncobs`
- 500 randomized round-trip payloads verified against `corncobs`
- **5 proptest properties** (~1280 random inputs): round-trip, interop
  encode/decode both directions, length bounds, decode-never-panics
- **2 fuzz targets**: `fuzz_decode` (arbitrary bytes → must not panic)
  and `fuzz_roundtrip` (encode→decode must match)
