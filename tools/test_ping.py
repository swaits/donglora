#!/usr/bin/env python3
"""DongLoRa test tool: ping, configure radio, listen for packets."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial"]
# ///

import struct
import serial
import sys
import time
from cobs import cobs


def cobs_frame(payload: bytes) -> bytes:
    return cobs.encode(payload) + b"\x00"


def read_frame(ser: serial.Serial) -> bytes | None:
    buf = b""
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b == b"\x00":
            break
        buf += b
    return cobs.decode(buf) if buf else None


# ── Postcard serialization helpers ──────────────────────────────────
# Postcard uses varint encoding for enum variants and integers.


def varint(n: int) -> bytes:
    """Encode unsigned varint (postcard style)."""
    out = []
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def encode_command(cmd: dict) -> bytes:
    """Encode a Command enum variant to postcard bytes."""
    kind = cmd["type"]
    if kind == "Ping":
        return varint(0)
    elif kind == "GetConfig":
        return varint(1)
    elif kind == "SetConfig":
        cfg = cmd["config"]
        return varint(2) + encode_radio_config(cfg)
    elif kind == "StartRx":
        return varint(3)
    elif kind == "StopRx":
        return varint(4)
    elif kind == "DisplayOn":
        return varint(7)
    elif kind == "DisplayOff":
        return varint(8)
    else:
        raise ValueError(f"Unknown command type: {kind}")


def encode_radio_config(cfg: dict) -> bytes:
    """Encode RadioConfig struct to postcard bytes."""
    # freq_hz: u32 as varint
    out = varint(cfg["freq_hz"])
    # bw: Bandwidth enum (u8 repr)
    out += varint(cfg["bw"])
    # sf: u8
    out += varint(cfg["sf"])
    # cr: CodingRate enum (u8 repr)
    out += varint(cfg["cr"])
    # sync_word: u16 as varint
    out += varint(cfg["sync_word"])
    # tx_power_dbm: i8 as zigzag varint
    out += zigzag(cfg["tx_power_dbm"])
    return out


def zigzag(n: int) -> bytes:
    """Encode signed int as zigzag varint."""
    return varint((n << 1) ^ (n >> 31) if n >= 0 else ((-n - 1) << 1) | 1)


def decode_response(data: bytes) -> dict:
    """Decode a Response enum variant from postcard bytes."""
    variant = data[0]
    rest = data[1:]
    if variant == 0:
        return {"type": "Pong"}
    elif variant == 1:
        return {"type": "Config", "raw": rest.hex()}
    elif variant == 2:
        # RxPacket: rssi(i16 zigzag), snr(i8 zigzag), payload(len-prefixed)
        rssi, rest = decode_zigzag_varint(rest)
        snr, rest = decode_zigzag_varint(rest)
        plen, rest = decode_varint(rest)
        payload = rest[:plen]
        return {
            "type": "RxPacket",
            "rssi": rssi,
            "snr": snr,
            "payload": payload,
        }
    elif variant == 3:
        return {"type": "TxDone"}
    elif variant == 4:
        return {"type": "Ok"}
    elif variant == 5:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    else:
        return {"type": f"Unknown({variant})", "raw": rest.hex()}


def decode_varint(data: bytes) -> tuple[int, bytes]:
    n = 0
    shift = 0
    for i, b in enumerate(data):
        n |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return n, data[i + 1 :]
    return n, b""


def decode_zigzag_varint(data: bytes) -> tuple[int, bytes]:
    n, rest = decode_varint(data)
    return (n >> 1) ^ -(n & 1), rest


# ── Main ────────────────────────────────────────────────────────────


def send_cmd(ser: serial.Serial, cmd: dict, label: str) -> dict | None:
    payload = encode_command(cmd)
    frame = cobs_frame(payload)
    print(f">>> {label}")
    ser.write(frame)
    ser.flush()
    resp_data = read_frame(ser)
    if resp_data is None:
        print("    timeout")
        return None
    resp = decode_response(resp_data)
    print(f"<<< {resp}")
    return resp


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
    print(f"Opening {port}")
    ser = serial.Serial(port, timeout=2)
    ser.reset_input_buffer()

    # Ping
    send_cmd(ser, {"type": "Ping"}, "Ping")

    # Configure radio: 910.525 MHz, BW 62.5k, SF7, CR 4/5
    config = {
        "freq_hz": 910_525_000,
        "bw": 6,  # Khz62 = 6
        "sf": 7,
        "cr": 1,  # Cr4_5 = 1
        "sync_word": 0x3444,
        "tx_power_dbm": 14,
    }
    send_cmd(ser, {"type": "SetConfig", "config": config}, "SetConfig 910.525/62.5k/SF7/CR4_5")

    # Start receiving
    send_cmd(ser, {"type": "StartRx"}, "StartRx")

    # Listen for packets
    print("\nListening for packets (Ctrl+C to stop)...\n")
    ser.timeout = None  # block forever
    try:
        while True:
            data = read_frame(ser)
            if data is None:
                continue
            resp = decode_response(data)
            if resp["type"] == "RxPacket":
                payload = resp["payload"]
                try:
                    text = payload.decode("utf-8", errors="replace")
                except Exception:
                    text = payload.hex()
                print(
                    f"  RSSI:{resp['rssi']:4d} dBm  "
                    f"SNR:{resp['snr']:3d} dB  "
                    f"len:{len(payload):3d}  "
                    f"payload: {text}"
                )
            else:
                print(f"  {resp}")
    except KeyboardInterrupt:
        print("\nStopping...")
        send_cmd(ser, {"type": "StopRx"}, "StopRx")


if __name__ == "__main__":
    main()
