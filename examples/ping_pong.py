#!/usr/bin/env python3
"""Two-dongle demo: one transmits, one receives.

Usage:
    python examples/ping_pong.py --role tx [PORT]
    python examples/ping_pong.py --role rx [PORT]
"""

import argparse
import sys
import time

import serial

import donglora as dl

parser = argparse.ArgumentParser(description="DongLoRa ping-pong demo")
parser.add_argument("--role", choices=["tx", "rx"], required=True)
parser.add_argument("port", nargs="?", help="Serial port (auto-detect if omitted)")
args = parser.parse_args()

try:
    ser = dl.connect(args.port)
    print(dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG))

    if args.role == "tx":
        print("Transmitting every 2 seconds (Ctrl+C to stop)...\n")
        seq = 0
        while True:
            msg = f"ping #{seq}"
            resp = dl.send(ser, "Transmit", payload=msg.encode())
            print(f"  TX: {msg!r}  → {resp['type']}")
            seq += 1
            time.sleep(2)

    else:
        print(dl.send(ser, "StartRx"))
        print("Receiving (Ctrl+C to stop)...\n")
        ser.timeout = 1
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
    try:
        dl.send(ser, "StopRx")
    except Exception:
        pass
    print("\nDone.")
except serial.SerialException as e:
    print(f"\nSerial error: {e}", file=sys.stderr)
    sys.exit(1)
