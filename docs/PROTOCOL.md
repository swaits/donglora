# DongLoRa USB Protocol Specification

DongLoRa communicates over USB CDC-ACM (virtual serial port) using
binary messages. No baud rate configuration is needed — USB handles
the transport.

**USB identifiers:** VID `1209`, PID `5741`

## Framing

Each message is serialized with [postcard](https://postcard.jamesmunns.com/)
and framed with [COBS](https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing):

```
[COBS-encoded postcard bytes] [0x00 sentinel]
```

COBS guarantees that `0x00` never appears in the encoded data, so the
sentinel byte unambiguously marks the end of each frame. Maximum frame
size is 512 bytes. USB packets are chunked at 64 bytes.

## Serialization (postcard)

Postcard is a compact binary format. The subset used by DongLoRa:

| Type | Encoding |
|------|----------|
| `u8` | Raw byte |
| `i8` | Raw byte (two's complement) |
| `u16`, `u32` | Varint (LEB128: 7 data bits per byte, MSB = continuation) |
| `i16`, `i32` | Zigzag then varint (`(n << 1) ^ (n >> bits-1)`) |
| Enum variant | Varint of 0-based variant index, then variant fields |
| `Option<T>` | `0x00` = None, `0x01` + T = Some |
| `Vec<u8, N>` | Varint length, then raw bytes |
| Struct | Fields in declaration order, no delimiters |

## Commands (Host → Firmware)

| Index | Command | Fields | Description |
|-------|---------|--------|-------------|
| 0 | `Ping` | — | Health check. Returns `Pong`. |
| 1 | `GetConfig` | — | Request current radio config. Returns `Config` or `Error(NotConfigured)`. |
| 2 | `SetConfig` | `RadioConfig` | Set radio parameters. Validated against hardware limits. Returns `Ok` or `Error(InvalidConfig)`. |
| 3 | `StartRx` | — | Enter continuous receive mode. Returns `Ok` or `Error`. |
| 4 | `StopRx` | — | Return to idle. Returns `Ok`. |
| 5 | `Transmit` | `Option<RadioConfig>`, `Vec<u8, 256>` | Transmit a packet. Optional per-packet config override. Returns `TxDone` or `Error`. Automatically resumes RX if it was active. |
| 6 | `DisplayOn` | — | Turn on the OLED display. |
| 7 | `DisplayOff` | — | Turn off the OLED display. |

## Responses (Firmware → Host)

| Index | Response | Fields | Description |
|-------|----------|--------|-------------|
| 0 | `Pong` | — | Reply to `Ping`. |
| 1 | `Config` | `RadioConfig` | Current radio configuration. |
| 2 | `RxPacket` | `rssi: i16`, `snr: i16`, `payload: Vec<u8, 256>` | Received packet with signal quality. |
| 3 | `TxDone` | — | Transmission complete. |
| 4 | `Ok` | — | Command succeeded (SetConfig, StartRx, StopRx). |
| 5 | `Error` | `ErrorCode` | Command failed. |

## RadioConfig

| Field | Type | Wire encoding | Valid range | Description |
|-------|------|---------------|-------------|-------------|
| `freq_hz` | `u32` | varint | 150,000,000 – 960,000,000 | Frequency in Hz |
| `bw` | `Bandwidth` | varint (0–9) | see table | Signal bandwidth |
| `sf` | `u8` | varint | 5 – 12 | Spreading factor |
| `cr` | `u8` | varint | 5 – 8 | Coding rate denominator (5 = CR 4/5) |
| `sync_word` | `u16` | varint | any | LoRa sync word (e.g. `0x3444`) |
| `tx_power_dbm` | `i8` | raw signed byte | board-dependent | TX power in dBm. `-128` = max power for this board. |

## Bandwidth

| Wire value | Bandwidth |
|------------|-----------|
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

## ErrorCode

| Wire value | Error | Meaning |
|------------|-------|---------|
| 0 | InvalidConfig | Radio config validation failed |
| 1 | RadioBusy | Radio is busy (e.g. RX restart failed) |
| 2 | TxTimeout | Transmission timed out |
| 3 | CrcError | CRC error on received packet |
| 4 | NotConfigured | Command requires SetConfig first |
| 5 | NoDisplay | Display command sent but no display attached |

## Worked Example

Configure the radio for 915 MHz, 125 kHz BW, SF7, CR 4/5, sync word `0x3444`,
14 dBm TX power.

### 1. Build the RadioConfig

| Field | Value | Varint bytes |
|-------|-------|-------------|
| `freq_hz` | 915,000,000 | `80 84 AF B4 03` |
| `bw` | 7 (125 kHz) | `07` |
| `sf` | 7 | `07` |
| `cr` | 5 (CR 4/5) | `05` |
| `sync_word` | 0x3444 | `C4 E8 00` |
| `tx_power_dbm` | 14 → zigzag 28 | `1C` |

### 2. Build the SetConfig command

Prepend the variant index for `SetConfig` (index 2):

```
02 80 84 AF B4 03 07 07 05 C4 E8 00 1C
```

### 3. COBS-encode and send

COBS encoding wraps the bytes so `0x00` never appears in the data,
then appends a `0x00` sentinel:

```
[COBS-encoded bytes] 00
```

Write the resulting bytes to the USB serial port. Read back a COBS
frame, decode it, and the first byte is the response variant index
(4 = `Ok`).

## Host Implementation Checklist

1. Open the USB serial port (find by VID:PID `1209:5741`)
2. Implement varint and zigzag encoding/decoding
3. Implement COBS encode/decode (use a library — available in every language)
4. Build `SetConfig` with your desired radio parameters
5. Send it, read back `Ok`
6. Send `StartRx`, read back `Ok`
7. Loop: read frames, decode `RxPacket` responses
8. To transmit: send `Transmit` with payload, read back `TxDone`

See `examples/` for working Python implementations.
