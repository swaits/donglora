#!/usr/bin/env python3
"""Two-way LoRa bridge over TCP — relay packets between two DongLoRa dongles
across any IP network (LAN, Tailscale, WireGuard, internet).

Architecture:
    [Radio A] <-USB-> [DongLoRa A] <-TCP-> [DongLoRa B] <-USB-> [Radio B]

Usage:
    # Machine A (server):
    python examples/lora_bridge.py --mode server --port 9100

    # Machine B (client):
    python examples/lora_bridge.py --mode client --host machineA --port 9100

Both sides:
    - Open local DongLoRa, configure radio, start RX
    - Forward received LoRa packets -> TCP -> remote side -> TX
    - Bidirectional: both sides receive AND transmit
"""
import argparse
import serial
import socket
import struct
import sys
import threading
import time

import donglora as dl


def tcp_send(sock: socket.socket, payload: bytes):
    """Send a length-prefixed message over TCP."""
    sock.sendall(struct.pack("<I", len(payload)) + payload)


def tcp_recv(sock: socket.socket) -> bytes | None:
    """Receive a length-prefixed message from TCP. Returns None on disconnect."""
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk
    length = struct.unpack("<I", header)[0]
    if length > 65536:
        return None  # sanity check
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return data


_ser_lock = threading.Lock()


def radio_to_tcp(ser: serial.Serial, sock: socket.socket):
    """Thread: forward LoRa RX packets to TCP."""
    ser.timeout = 1
    while True:
        try:
            with _ser_lock:
                data = dl.read_frame(ser)
            if data is None:
                continue
            resp = dl.decode_response(data)
            if resp["type"] == "RxPacket":
                payload = resp["payload"]
                snr = resp["snr"]
                rssi = resp["rssi"]
                sf = dl.DEFAULT_CONFIG["sf"]
                min_snr = -2.5 * (sf - 4)

                # Grade per PROTOCOL.md — drop likely-corrupt packets
                if snr < -32 or snr > 32:
                    grade = "INVALID"
                elif snr < min_snr:
                    grade = "UNRELIABLE"
                elif snr < min_snr + 3:
                    grade = "MARGINAL"
                else:
                    grade = "GOOD"

                if grade in ("INVALID", "UNRELIABLE"):
                    print(f"  RX drop len:{len(payload):3d}  rssi:{rssi}dBm  snr:{snr}dB  [{grade}]")
                    continue

                tag = f"  [{grade}]" if grade == "MARGINAL" else ""
                print(f"  RX→TCP  len:{len(payload):3d}  rssi:{rssi}dBm  snr:{snr}dB{tag}")
                tcp_send(sock, payload)
        except (serial.SerialException, OSError) as e:
            print(f"  [radio→tcp error: {e}]")
            break


def tcp_to_radio(ser: serial.Serial, sock: socket.socket):
    """Thread: forward TCP packets to LoRa TX."""
    while True:
        try:
            payload = tcp_recv(sock)
            if payload is None:
                print("  [TCP disconnected]")
                break
            print(f"  TCP→TX  len:{len(payload):3d}")
            with _ser_lock:
                dl.send(ser, "Transmit", payload=payload)
        except (serial.SerialException, OSError) as e:
            print(f"  [tcp→radio error: {e}]")
            break


def run_bridge(ser: serial.Serial, sock: socket.socket):
    """Run bidirectional bridge between serial and TCP."""
    print("Bridge active — forwarding packets bidirectionally\n")

    t1 = threading.Thread(target=radio_to_tcp, args=(ser, sock), daemon=True)
    t2 = threading.Thread(target=tcp_to_radio, args=(ser, sock), daemon=True)
    t1.start()
    t2.start()

    try:
        while t1.is_alive() and t2.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("\nBridge stopped.")


def main():
    parser = argparse.ArgumentParser(description="DongLoRa two-way LoRa bridge over TCP")
    parser.add_argument("--mode", choices=["server", "client"], required=True)
    parser.add_argument("--host", default="localhost", help="Remote host (client mode)")
    parser.add_argument("--port", type=int, default=9100, help="TCP port")
    parser.add_argument("--serial", default=None, help="Serial port (auto-detect if omitted)")
    args = parser.parse_args()

    try:
        # Open DongLoRa
        ser = dl.connect(args.serial)
        print(dl.send(ser, "SetConfig", config=dl.DEFAULT_CONFIG))
        print(dl.send(ser, "StartRx"))

        # Establish TCP connection
        if args.mode == "server":
            print(f"Listening on port {args.port}...")
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", args.port))
            srv.listen(1)
            sock, addr = srv.accept()
            print(f"Connected from {addr}")
            srv.close()
        else:
            print(f"Connecting to {args.host}:{args.port}...")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((args.host, args.port))
            print("Connected")

        run_bridge(ser, sock)

    except KeyboardInterrupt:
        print("\nInterrupted.")
    except serial.SerialException as e:
        print(f"\nSerial error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"\nNetwork error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
