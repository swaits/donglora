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
cargo test -p donglora-cobs
```

Tests include:
- 18 canonical COBS vectors (Wikipedia / IEEE/ACM spec)
- Round-trip verification for various payload sizes
- 8 interop tests cross-validating against `corncobs` (dev-dependency)
- 500 randomized round-trip payloads verified against `corncobs`
