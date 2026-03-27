#!/usr/bin/env python3
"""DongLoRa test tool: ping, configure radio, listen for packets."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial"]
# ///

import glob
import struct
import serial
import sys
import time
from cobs import cobs

# Open-source VID 1209, PID "WA" (0x5741)
USB_VID_PID = "1209:5741"


def find_serial_port() -> str | None:
    """Find the serial port for our USB device."""
    import subprocess

    # Try to find by USB VID:PID
    for path in sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/ttyUSB*")):
        try:
            result = subprocess.run(
                ["udevadm", "info", "--query=property", f"--name={path}"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            vid = ""
            pid = ""
            for line in result.stdout.splitlines():
                if line.startswith("ID_VENDOR_ID="):
                    vid = line.split("=", 1)[1].lower()
                elif line.startswith("ID_MODEL_ID="):
                    pid = line.split("=", 1)[1].lower()
            if f"{vid}:{pid}" == USB_VID_PID:
                return path
        except Exception:
            continue

    # Fallback: first ttyACM device
    ports = sorted(glob.glob("/dev/ttyACM*"))
    return ports[0] if ports else None


def wait_for_device() -> str:
    """Poll until the USB device appears."""
    print("Waiting for DongLoRa...", end="", flush=True)
    while True:
        port = find_serial_port()
        if port:
            print(f" found {port}")
            time.sleep(0.3)  # let the device settle
            return port
        print(".", end="", flush=True)
        time.sleep(0.5)


def open_serial(port: str) -> serial.Serial:
    return serial.Serial(port, timeout=2)


# ── COBS framing ───────────────────────────────────────────────────


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


# ── Postcard serialization ─────────────────────────────────────────


def varint(n: int) -> bytes:
    out = []
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def zigzag(n: int) -> bytes:
    return varint((n << 1) ^ (n >> 31) if n >= 0 else ((-n - 1) << 1) | 1)


def encode_radio_config(cfg: dict) -> bytes:
    out = varint(cfg["freq_hz"])
    out += varint(cfg["bw"])
    out += varint(cfg["sf"])
    out += varint(cfg["cr"])
    out += varint(cfg["sync_word"])
    out += zigzag(cfg["tx_power_dbm"])
    return out


def encode_command(cmd: dict) -> bytes:
    kind = cmd["type"]
    if kind == "Ping":
        return varint(0)
    elif kind == "GetConfig":
        return varint(1)
    elif kind == "SetConfig":
        return varint(2) + encode_radio_config(cmd["config"])
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


def decode_varint(data: bytes) -> tuple[int, bytes]:
    n, shift = 0, 0
    for i, b in enumerate(data):
        n |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return n, data[i + 1 :]
    return n, b""


def decode_zigzag_varint(data: bytes) -> tuple[int, bytes]:
    n, rest = decode_varint(data)
    return (n >> 1) ^ -(n & 1), rest


def decode_response(data: bytes) -> dict:
    variant = data[0]
    rest = data[1:]
    if variant == 0:
        return {"type": "Pong"}
    elif variant == 1:
        return {"type": "Config", "raw": rest.hex()}
    elif variant == 2:
        rssi, rest = decode_zigzag_varint(rest)
        snr, rest = decode_zigzag_varint(rest)
        plen, rest = decode_varint(rest)
        payload = rest[:plen]
        return {"type": "RxPacket", "rssi": rssi, "snr": snr, "payload": payload}
    elif variant == 3:
        return {"type": "TxDone"}
    elif variant == 4:
        return {"type": "Ok"}
    elif variant == 5:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    else:
        return {"type": f"Unknown({variant})", "raw": rest.hex()}


# ── Main ───────────────────────────────────────────────────────────


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


RADIO_CONFIG = {
    "freq_hz": 910_525_000,
    "bw": 6,  # Khz62 = variant index 6
    "sf": 7,
    "cr": 0,  # Cr4_5 = variant index 0
    "sync_word": 0x3444,
    "tx_power_dbm": 14,
}


def configure_and_listen(ser: serial.Serial):
    send_cmd(ser, {"type": "Ping"}, "Ping")
    send_cmd(ser, {"type": "SetConfig", "config": RADIO_CONFIG}, "SetConfig 910.525/62.5k/SF7/CR4_5")
    send_cmd(ser, {"type": "StartRx"}, "StartRx")

    print("\nListening for packets (Ctrl+C to stop)...\n")
    ser.timeout = None
    while True:
        data = read_frame(ser)
        if data is None:
            raise ConnectionError("device disconnected")
        resp = decode_response(data)
        if resp["type"] == "RxPacket":
            payload = resp["payload"]
            try:
                text = payload.decode("utf-8", errors="replace")
            except Exception:
                text = payload.hex()
            print(
                f"  RSSI:{resp['rssi']:4d}dBm  "
                f"SNR:{resp['snr']:3d}dB  "
                f"len:{len(payload):3d}  "
                f"{text}"
            )
        else:
            print(f"  {resp}")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None

    while True:
        if port is None:
            port = wait_for_device()

        try:
            print(f"Opening {port}")
            ser = open_serial(port)
            ser.reset_input_buffer()
            configure_and_listen(ser)
        except (serial.SerialException, ConnectionError, OSError) as e:
            print(f"\nDisconnected: {e}")
            print("Will reconnect when device reappears...")
            port = None
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            try:
                ser.timeout = 2
                send_cmd(ser, {"type": "StopRx"}, "StopRx")
            except Exception:
                pass
            break


if __name__ == "__main__":
    main()
