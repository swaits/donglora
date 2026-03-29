#!/usr/bin/env python3
"""Two-dongle demo: one transmits, one receives.

Usage:
    uv run examples/ping_pong.py --role tx [PORT]
    uv run examples/ping_pong.py --role rx [PORT]
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial"]
# ///

import argparse
import sys
import time

sys.path.insert(0, __import__("pathlib").Path(__file__).parent.as_posix())
import donglora as dl  # noqa: E402

parser = argparse.ArgumentParser(description="DongLoRa ping-pong demo")
parser.add_argument("--role", choices=["tx", "rx"], required=True)
parser.add_argument("port", nargs="?", help="Serial port (auto-detect if omitted)")
args = parser.parse_args()

ser = dl.connect(args.port)
print(dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG))

if args.role == "tx":
    print("Transmitting every 2 seconds (Ctrl+C to stop)...\n")
    seq = 0
    try:
        while True:
            msg = f"ping #{seq}"
            resp = dl.send(ser, "Transmit", payload=msg.encode())
            print(f"  TX: {msg!r}  → {resp['type']}")
            seq += 1
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nDone.")

else:
    print(dl.send(ser, "StartRx"))
    print("Receiving (Ctrl+C to stop)...\n")
    ser.timeout = 1
    try:
        while True:
            data = dl.read_frame(ser)
            if data is None:
                continue
            resp = dl.decode_response(data)
            if resp["type"] == "RxPacket":
                p = resp["payload"]
                text = p.decode("utf-8", errors="replace")
                print(f"  RX: {text!r}  RSSI:{resp['rssi']}dBm  SNR:{resp['snr']}dB")
    except KeyboardInterrupt:
        dl.send(ser, "StopRx")
        print("\nDone.")
