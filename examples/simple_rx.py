#!/usr/bin/env python3
"""Receive LoRa packets and print them.

Usage:
    uv run examples/simple_rx.py [PORT]
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial"]
# ///

import serial
import sys

sys.path.insert(0, __import__("pathlib").Path(__file__).parent.as_posix())
import donglora as dl  # noqa: E402

try:
    ser = dl.connect(sys.argv[1] if len(sys.argv) > 1 else None)
    print(dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG))
    print(dl.send(ser, "StartRx"))

    print("\nListening (Ctrl+C to stop)...\n")
    ser.timeout = 1

    while True:
        data = dl.read_frame(ser)
        if data is None:
            continue
        resp = dl.decode_response(data)
        if resp["type"] == "RxPacket":
            p = resp["payload"]
            print(f"  RSSI:{resp['rssi']:4d}dBm  SNR:{resp['snr']:3d}dB  len:{len(p):3d}  {p.hex()}")
except KeyboardInterrupt:
    try:
        dl.send(ser, "StopRx")
    except Exception:
        pass
    print("\nDone.")
except serial.SerialException as e:
    print(f"\nSerial error: {e}", file=sys.stderr)
    sys.exit(1)
