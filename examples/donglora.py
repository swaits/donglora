"""DongLoRa host library — connect, configure, send/receive LoRa packets.

This is a minimal helper for the example scripts. It implements the
DongLoRa USB protocol (COBS-framed fixed-size LE) just enough to be useful.
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


# ── Fixed-size LE encoding ────────────────────────────────────────

def encode_config(cfg: dict) -> bytes:
    """Encode a RadioConfig to 10 fixed-size LE bytes."""
    return struct.pack("<IBBBHB",
        cfg["freq_hz"],
        cfg["bw"],
        cfg["sf"],
        cfg["cr"],
        cfg["sync_word"],
        cfg["tx_power_dbm"] & 0xFF,  # i8 as unsigned byte
    )


def encode_command(cmd: str, **kwargs) -> bytes:
    """Encode a command to fixed-size LE bytes."""
    tags = {
        "Ping": 0, "GetConfig": 1, "SetConfig": 2, "StartRx": 3,
        "StopRx": 4, "Transmit": 5, "DisplayOn": 6, "DisplayOff": 7,
    }
    out = bytes([tags[cmd]])
    if cmd == "SetConfig":
        out += encode_config(kwargs["config"])
    elif cmd == "Transmit":
        config = kwargs.get("config")
        if config is None:
            out += b"\x00"
        else:
            out += b"\x01" + encode_config(config)
        payload = kwargs["payload"]
        out += struct.pack("<H", len(payload)) + payload
    return out


# ── Response decoding ────────────────────────────────────────────

def decode_response(data: bytes) -> dict:
    """Decode a fixed-size LE response."""
    if not data:
        return {"type": "Empty"}
    tag = data[0]
    rest = data[1:]
    if tag == 0:
        return {"type": "Pong"}
    elif tag == 1:
        if len(rest) >= 10:
            freq_hz, bw, sf, cr, sync_word, pwr = struct.unpack_from("<IBBBHB", rest, 0)
            tx_power_dbm = struct.unpack_from("<b", rest, 9)[0]
            return {"type": "Config", "freq_hz": freq_hz, "bw": bw, "sf": sf,
                    "cr": cr, "sync_word": sync_word, "tx_power_dbm": tx_power_dbm}
        return {"type": "Config", "raw": rest.hex()}
    elif tag == 2:
        rssi = struct.unpack_from("<h", rest, 0)[0]
        snr = struct.unpack_from("<h", rest, 2)[0]
        plen = struct.unpack_from("<H", rest, 4)[0]
        payload = rest[6:6 + plen]
        return {"type": "RxPacket", "rssi": rssi, "snr": snr, "payload": payload}
    elif tag == 3:
        return {"type": "TxDone"}
    elif tag == 4:
        return {"type": "Ok"}
    elif tag == 5:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    else:
        return {"type": f"Unknown({tag})"}


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


# Sentinel: set TX power to the board's maximum
TX_POWER_MAX = -128  # i8::MIN on the wire

# Default radio config: 915 MHz, 125 kHz BW, SF7, CR 4/5, max power
DEFAULT_CONFIG = {
    "freq_hz": 915_000_000,
    "bw": 7,        # 125 kHz
    "sf": 7,
    "cr": 5,         # CR 4/5
    "sync_word": 0x1424,
    "tx_power_dbm": TX_POWER_MAX,
}
