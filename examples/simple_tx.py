#!/usr/bin/env python3
"""Transmit a single LoRa packet.

Usage:
    uv run examples/simple_tx.py [PORT] [MESSAGE]
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial"]
# ///

import serial
import sys

sys.path.insert(0, __import__("pathlib").Path(__file__).parent.as_posix())
import donglora as dl  # noqa: E402

port = None
message = "Hello from DongLoRa!"

args = sys.argv[1:]
if args and not args[0].startswith("/dev"):
    message = " ".join(args)
elif args:
    port = args[0]
    if len(args) > 1:
        message = " ".join(args[1:])

try:
    ser = dl.connect(port)
    print(dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG))
    print(dl.send(ser, "Transmit", payload=message.encode()))
    print(f"Sent: {message!r}")
except serial.SerialException as e:
    print(f"\nSerial error: {e}", file=sys.stderr)
    sys.exit(1)
