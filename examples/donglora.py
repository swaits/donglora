"""DongLoRa host library — connect, configure, send/receive LoRa packets.

This is a minimal helper for the example scripts. It implements the
DongLoRa USB protocol (COBS-framed postcard) just enough to be useful.
See docs/PROTOCOL.md for the full specification.
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial"]
# ///

import glob
import struct
import subprocess

import serial
import time
from cobs import cobs

# ── USB device discovery ──────────────────────────────────────────

USB_VID_PID = "1209:5741"


def find_port() -> str | None:
    """Find the DongLoRa serial port by USB VID:PID."""
    for path in sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*")):
        try:
            result = subprocess.run(
                ["udevadm", "info", "--query=property", f"--name={path}"],
                capture_output=True, text=True, timeout=2,
            )
            props = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            vid = props.get("ID_VENDOR_ID", "").lower()
            pid = props.get("ID_MODEL_ID", "").lower()
            if f"{vid}:{pid}" == USB_VID_PID:
                return path
        except Exception:
            continue
    ports = sorted(glob.glob("/dev/ttyACM*"))
    return ports[0] if ports else None


def wait_for_device() -> str:
    """Block until a DongLoRa device appears."""
    print("Waiting for DongLoRa...", end="", flush=True)
    while True:
        port = find_port()
        if port:
            print(f" found {port}")
            time.sleep(0.3)
            return port
        print(".", end="", flush=True)
        time.sleep(0.5)


# ── COBS framing ─────────────────────────────────────────────────

def cobs_encode(data: bytes) -> bytes:
    return cobs.encode(data) + b"\x00"


def read_frame(ser: serial.Serial) -> bytes | None:
    """Read one COBS frame. Returns decoded bytes or None on timeout."""
    buf = b""
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b == b"\x00":
            break
        buf += b
    if not buf:
        return None
    try:
        return cobs.decode(buf)
    except cobs.DecodeError:
        return None


# ── Postcard encoding ────────────────────────────────────────────

def varint(n: int) -> bytes:
    out = []
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def zigzag(n: int) -> bytes:
    return varint((n << 1) ^ (n >> 31) if n >= 0 else ((-n - 1) << 1) | 1)


def decode_varint(data: bytes) -> tuple[int, bytes]:
    n, shift = 0, 0
    for i, b in enumerate(data):
        n |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return n, data[i + 1:]
    return n, b""


def decode_zigzag(data: bytes) -> tuple[int, bytes]:
    n, rest = decode_varint(data)
    return (n >> 1) ^ -(n & 1), rest


# ── Command encoding ─────────────────────────────────────────────

def encode_config(cfg: dict) -> bytes:
    """Encode a RadioConfig dict to postcard bytes.

    Postcard wire format: u8/i8 are raw bytes, u16/u32 are varint,
    i16/i32 are zigzag+varint, enums are varint variant index.
    """
    out = varint(cfg["freq_hz"])              # u32: varint
    out += varint(cfg["bw"])                  # enum: varint variant index
    out += struct.pack("B", cfg["sf"])        # u8: raw byte
    out += struct.pack("B", cfg["cr"])        # u8: raw byte
    out += varint(cfg["sync_word"])           # u16: varint
    out += struct.pack("b", cfg["tx_power_dbm"])  # i8: raw signed byte
    return out


def encode_command(cmd: str, **kwargs) -> bytes:
    """Encode a command name + kwargs to postcard bytes."""
    commands = {
        "Ping": 0, "GetConfig": 1, "SetConfig": 2, "StartRx": 3,
        "StopRx": 4, "Transmit": 5, "DisplayOn": 6, "DisplayOff": 7,
    }
    idx = commands[cmd]
    out = varint(idx)
    if cmd == "SetConfig":
        out += encode_config(kwargs["config"])
    elif cmd == "Transmit":
        config = kwargs.get("config")
        if config is None:
            out += b"\x00"
        else:
            out += b"\x01" + encode_config(config)
        payload = kwargs["payload"]
        out += varint(len(payload)) + payload
    return out


# ── Response decoding ────────────────────────────────────────────

def decode_response(data: bytes) -> dict:
    """Decode a postcard-encoded response into a dict."""
    if not data:
        return {"type": "Empty"}
    variant = data[0]
    rest = data[1:]
    if variant == 0:
        return {"type": "Pong"}
    elif variant == 1:
        return {"type": "Config", "raw": rest.hex()}
    elif variant == 2:
        rssi, rest = decode_zigzag(rest)
        snr, rest = decode_zigzag(rest)
        plen, rest = decode_varint(rest)
        return {"type": "RxPacket", "rssi": rssi, "snr": snr, "payload": rest[:plen]}
    elif variant == 3:
        return {"type": "TxDone"}
    elif variant == 4:
        return {"type": "Ok"}
    elif variant == 5:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    else:
        return {"type": f"Unknown({variant})"}


# ── High-level helpers ───────────────────────────────────────────

def send(ser: serial.Serial, cmd: str, **kwargs) -> dict:
    """Send a command and return the response."""
    ser.write(cobs_encode(encode_command(cmd, **kwargs)))
    ser.flush()
    data = read_frame(ser)
    if data is None:
        return {"type": "Timeout"}
    return decode_response(data)


def connect(port: str | None = None, timeout: float = 2.0) -> serial.Serial:
    """Open a connection to a DongLoRa device."""
    if port is None:
        port = wait_for_device()
    ser = serial.Serial(port, timeout=timeout)
    ser.reset_input_buffer()
    return ser


# Default radio config: 915 MHz, 125 kHz BW, SF7, CR 4/5
DEFAULT_CONFIG = {
    "freq_hz": 915_000_000,
    "bw": 7,        # 125 kHz
    "sf": 7,
    "cr": 5,         # CR 4/5
    "sync_word": 0x1424,
    "tx_power_dbm": 14,
}
