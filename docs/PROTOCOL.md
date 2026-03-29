# DongLoRa USB Protocol

DongLoRa communicates over USB CDC-ACM (virtual serial port).
No baud rate configuration needed.

**USB identifiers:** VID `1209`, PID `5741`

## Framing

Each message is [COBS](https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing)-encoded
and terminated with a `0x00` sentinel byte:

```
[COBS-encoded bytes] [0x00]
```

COBS guarantees `0x00` never appears in the encoded data, so the
sentinel unambiguously marks frame boundaries. USB packets are
chunked at 64 bytes.

## Encoding

All integers are **fixed-size little-endian**. No variable-length
encoding. Every field has a known size at a known offset.

| Type | Size | Encoding |
|------|------|----------|
| `u8` | 1 | Raw byte |
| `i8` | 1 | Raw byte (two's complement) |
| `u16` | 2 | Little-endian |
| `i16` | 2 | Little-endian (two's complement) |
| `u32` | 4 | Little-endian |

## RadioConfig (10 bytes)

| Offset | Size | Field | Type | Valid range |
|--------|------|-------|------|-------------|
| 0 | 4 | `freq_hz` | u32 LE | 150,000,000 – 960,000,000 |
| 4 | 1 | `bw` | u8 | 0–9 (see bandwidth table) |
| 5 | 1 | `sf` | u8 | 5–12 |
| 6 | 1 | `cr` | u8 | 5–8 (coding rate denominator) |
| 7 | 2 | `sync_word` | u16 LE | any |
| 9 | 1 | `tx_power_dbm` | i8 | board-dependent, or `-128` for max |

Set `tx_power_dbm` to `-128` (0x80) to use the board's maximum
TX power. The firmware resolves this to the actual hardware max.

## Commands (Host → Firmware)

Each command is a tag byte followed by fixed-size fields.

| Tag | Command | Payload |
|-----|---------|---------|
| 0 | Ping | — |
| 1 | GetConfig | — |
| 2 | SetConfig | RadioConfig (10 bytes) |
| 3 | StartRx | — |
| 4 | StopRx | — |
| 5 | Transmit | has_config (1) + [RadioConfig if 1] + len (u16 LE) + payload |
| 6 | DisplayOn | — |
| 7 | DisplayOff | — |

## Responses (Firmware → Host)

| Tag | Response | Payload |
|-----|----------|---------|
| 0 | Pong | — |
| 1 | Config | RadioConfig (10 bytes) |
| 2 | RxPacket | rssi (i16 LE) + snr (i16 LE) + len (u16 LE) + payload |
| 3 | TxDone | — |
| 4 | Ok | — |
| 5 | Error | code (u8) |

## Bandwidth

| Value | Bandwidth |
|-------|-----------|
| 0 | 7.8 kHz |
| 1 | 10.4 kHz |
| 2 | 15.6 kHz |
| 3 | 20.8 kHz |
| 4 | 31.25 kHz |
| 5 | 41.7 kHz |
| 6 | 62.5 kHz |
| 7 | 125 kHz |
| 8 | 250 kHz |
| 9 | 500 kHz |

## Error Codes

| Value | Error | Meaning |
|-------|-------|---------|
| 0 | InvalidConfig | Radio config validation failed |
| 1 | RadioBusy | Radio busy (e.g. RX restart failed) |
| 2 | TxTimeout | Transmission timed out |
| 3 | CrcError | CRC error on received packet |
| 4 | NotConfigured | SetConfig required first |
| 5 | NoDisplay | No display attached |

## Worked Example

Configure for 915 MHz, 125 kHz BW, SF7, CR 4/5, max TX power:

### 1. Build the bytes

```python
import struct
config = struct.pack("<IBBBHB",
    915_000_000,  # freq_hz
    7,            # bw (125 kHz)
    7,            # sf
    5,            # cr (4/5)
    0x1424,       # sync_word
    0x80,         # tx_power_dbm (-128 = max)
)
command = b"\x02" + config  # tag 2 = SetConfig
```

Raw bytes: `02 00 93 87 36 07 07 05 24 14 80`

### 2. COBS-encode and send

COBS-encode the bytes, append `0x00`, write to USB serial port.
Read back the response, COBS-decode it. First byte `0x04` = Ok.

## Host Implementation Checklist

1. Open USB serial port (find by VID:PID `1209:5741`)
2. Implement COBS encode/decode (libraries exist for every language)
3. Pack commands with `struct.pack` or equivalent — all fields are fixed-size LE
4. Send `SetConfig`, read back `Ok`
5. Send `StartRx`, read back `Ok`
6. Loop: read frames, decode `RxPacket` (rssi, snr, payload at known offsets)
7. To transmit: send `Transmit`, read back `TxDone`

See `examples/` for working Python implementations.
