#!/usr/bin/env python3
"""Exercise every DongLoRa command to verify the API works.

Usage:
    uv run examples/all_commands.py [PORT]
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

    print("── Ping ──")
    print(dl.send(ser, "Ping"))

    print("\n── SetConfig ──")
    print(dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG))

    print("\n── GetConfig ──")
    print(dl.send(ser, "GetConfig"))

    print("\n── StartRx ──")
    print(dl.send(ser, "StartRx"))

    print("\n── StopRx ──")
    print(dl.send(ser, "StopRx"))

    print("\n── Transmit ──")
    print(dl.send(ser, "Transmit", payload=b"Hello from all_commands.py!"))

    print("\n── DisplayOff ──")
    print(dl.send(ser, "DisplayOff"))

    print("\n── DisplayOn ──")
    print(dl.send(ser, "DisplayOn"))

    print("\n── GetMac ──")
    print(dl.send(ser, "GetMac"))

    print("\nAll 9 commands exercised successfully.")

except KeyboardInterrupt:
    print("\nInterrupted.")
except serial.SerialException as e:
    print(f"\nSerial error: {e}", file=sys.stderr)
    sys.exit(1)
