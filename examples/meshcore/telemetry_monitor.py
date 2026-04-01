#!/usr/bin/env python3
"""MeshCore repeater telemetry monitor.

Periodically logs into configured repeaters and fetches telemetry data
(battery voltage, temperature, etc.). Uses route escalation to minimise
flooding: last-known route → zero-hop direct → flood, then learns the
return path for next time.

Configuration lives in ~/.donglora/telemetry.json:

    {
        "repeaters": [
            {
                "name": "Hilltop-1",
                "password": "guest123"
            }
        ],
        "poll_interval_secs": 3600
    }

The "pubkey" field is optional.  If missing (or empty), the monitor
listens for MeshCore ADVERTs, matches by name, fills in the pubkey
automatically, and saves the config back to disk.
"""
import hashlib
import hmac
import json
import os
import random
import struct
import sys
import time
from pathlib import Path

import serial
from cobs import cobs
from Crypto.Cipher import AES
from nacl.bindings import crypto_scalarmult
from nacl.signing import SigningKey, VerifyKey

import donglora as dl


# ── Constants ─────────────────────────────────────────────────────

DATA_DIR = Path.home() / ".donglora"
CONFIG_FILE = DATA_DIR / "telemetry.json"
KEY_FILE = DATA_DIR / "telemetry_key.bin"
STATE_FILE = DATA_DIR / "telemetry_state.json"

DEFAULT_POLL_INTERVAL = 3600  # 1 hour

# MeshCore protocol constants
REQ_TYPE_GET_TELEMETRY_DATA = 0x03
TELEM_PERM_BASE = 0x01
TELEM_PERM_LOCATION = 0x02
TELEM_PERM_ENVIRONMENT = 0x04

# Timeouts and retries
LOGIN_TIMEOUT = 15.0   # seconds to wait for login response
TELEM_TIMEOUT = 15.0   # seconds to wait for telemetry response
TX_SETTLE = 1.0        # delay between transmissions
FLOOD_RETRIES = 3      # retry flood login/telemetry this many times

RADIO_CONFIG = {
    "freq_hz": 910_525_000,
    "bw": 6,            # 62.5 kHz
    "sf": 7,
    "cr": 5,            # CR 4/5
    "sync_word": 0x3444,
    "tx_power_dbm": -128,  # TX_POWER_MAX
}


# ── ANSI helpers ──────────────────────────────────────────────────

RST = "\033[0m"
DIM = "\033[2m"
RED = "\033[31m"
GRN = "\033[32m"
YEL = "\033[33m"
CYN = "\033[36m"
BCYN = "\033[1;36m"
BGRN = "\033[1;32m"
BWHT = "\033[1;37m"


# ── Identity ──────────────────────────────────────────────────────

_signing_key: SigningKey | None = None
_verify_key: VerifyKey | None = None
_pubkey_bytes: bytes = b""


def _init_identity():
    global _signing_key, _verify_key, _pubkey_bytes
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if KEY_FILE.is_file():
        seed = KEY_FILE.read_bytes()
        if len(seed) == 32:
            _signing_key = SigningKey(seed)
            print(f"  {DIM}Loaded keypair from {KEY_FILE}{RST}")
        else:
            _signing_key = SigningKey.generate()
            KEY_FILE.write_bytes(bytes(_signing_key))
    else:
        _signing_key = SigningKey.generate()
        KEY_FILE.write_bytes(bytes(_signing_key))
        print(f"  {BWHT}Generated new keypair → {KEY_FILE}{RST}")

    _verify_key = _signing_key.verify_key
    _pubkey_bytes = bytes(_verify_key)
    print(f"  {DIM}Pubkey: {_pubkey_bytes.hex()}{RST}")
    print(f"  {DIM}Node hash: 0x{_pubkey_bytes[0]:02x}{RST}")


def _my_hash() -> int:
    return _pubkey_bytes[0]


# ── Crypto ────────────────────────────────────────────────────────


def _ecdh_shared_secret(peer_ed25519_pub: bytes) -> bytes:
    my_x25519 = bytes(_signing_key.to_curve25519_private_key())
    peer_verify = VerifyKey(peer_ed25519_pub)
    peer_x25519 = bytes(peer_verify.to_curve25519_public_key())
    return crypto_scalarmult(my_x25519, peer_x25519)


def _encrypt(shared_secret: bytes, plaintext: bytes) -> bytes:
    """Encrypt-then-MAC. Returns mac(2) + ciphertext."""
    pad_len = (16 - len(plaintext) % 16) % 16
    plaintext += b"\x00" * pad_len
    cipher = AES.new(shared_secret[:16], AES.MODE_ECB)
    ciphertext = b""
    for i in range(0, len(plaintext), 16):
        ciphertext += cipher.encrypt(plaintext[i : i + 16])
    mac = hmac.new(shared_secret[:32], ciphertext, hashlib.sha256).digest()[:2]
    return mac + ciphertext


def _verify_and_decrypt(shared_secret: bytes, mac_bytes: bytes, ciphertext: bytes) -> bytes | None:
    computed = hmac.new(shared_secret[:32], ciphertext, hashlib.sha256).digest()[:2]
    if computed != mac_bytes:
        return None
    cipher = AES.new(shared_secret[:16], AES.MODE_ECB)
    plaintext = b""
    for i in range(0, len(ciphertext), 16):
        plaintext += cipher.decrypt(ciphertext[i : i + 16])
    return plaintext


# ── Route table ───────────────────────────────────────────────────
# pubkey_hex → (path_hops: list[bytes], hash_size: int)

_route_table: dict[str, tuple[list[bytes], int]] = {}


MIN_HASH_SIZE = 2  # always use 2-byte routing minimum


def _learn_route(pubkey_hex: str, path_hops: list[bytes], hash_size: int):
    """Learn a return route from an incoming packet's path (reversed)."""
    if hash_size < MIN_HASH_SIZE:
        return  # reject 1-byte routes
    existing = _route_table.get(pubkey_hex)
    if existing is not None:
        _, existing_hs = existing
        if hash_size < existing_hs:
            return
    _route_table[pubkey_hex] = (list(reversed(path_hops)), hash_size)


def _get_route(pubkey_hex: str) -> tuple[list[bytes], int] | None:
    return _route_table.get(pubkey_hex)


# ── Persistent state ─────────────────────────────────────────────

_state: dict = {"routes": {}}


def _load_state():
    global _state
    if STATE_FILE.is_file():
        try:
            with open(STATE_FILE) as f:
                loaded = json.load(f)
            _state.update(loaded)
            # Restore routes from state
            for pk_hex, route_data in _state.get("routes", {}).items():
                hops = [bytes.fromhex(h) for h in route_data["hops"]]
                _route_table[pk_hex] = (hops, route_data["hash_size"])
            print(f"  {DIM}Loaded state ({len(_route_table)} routes){RST}")
        except Exception as e:
            print(f"  {YEL}Failed to load state: {e}{RST}")


def _save_state():
    try:
        # Serialise routes
        routes = {}
        for pk_hex, (hops, hs) in _route_table.items():
            routes[pk_hex] = {"hops": [h.hex() for h in hops], "hash_size": hs}
        _state["routes"] = routes

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(_state, f, indent=2)
        tmp.rename(STATE_FILE)
    except Exception as e:
        print(f"  {RED}Failed to save state: {e}{RST}")


# ── Serial / USB ──────────────────────────────────────────────────

def open_connection(port: str | None = None):
    """Open a DongLoRa connection (mux auto-detected, falls back to USB)."""
    return dl.connect(port=port, timeout=2)


# ── COBS framing ─────────────────────────────────────────────────


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
    if not buf:
        return None
    try:
        return cobs.decode(buf)
    except cobs.DecodeError:
        return None


# ── Command encoding / response decoding ─────────────────────────


def encode_radio_config(cfg: dict) -> bytes:
    return struct.pack(
        "<IBBBHBHB",
        cfg["freq_hz"], cfg["bw"], cfg["sf"], cfg["cr"],
        cfg["sync_word"], cfg["tx_power_dbm"] & 0xFF,
        cfg.get("preamble_len", 0), cfg.get("cad", 1),
    )


def encode_command(cmd: dict) -> bytes:
    kind = cmd["type"]
    tags = {
        "Ping": 0, "GetConfig": 1, "SetConfig": 2, "StartRx": 3,
        "StopRx": 4, "Transmit": 5, "DisplayOn": 6, "DisplayOff": 7,
    }
    out = bytes([tags[kind]])
    if kind == "SetConfig":
        out += encode_radio_config(cmd["config"])
    elif kind == "Transmit":
        config = cmd.get("config")
        if config is None:
            out += b"\x00"
        else:
            out += b"\x01" + encode_radio_config(config)
        payload = cmd["payload"]
        out += struct.pack("<H", len(payload)) + payload
    return out


def decode_response(data: bytes) -> dict:
    if not data:
        return {"type": "Empty"}
    tag = data[0]
    rest = data[1:]
    if tag == 0:
        return {"type": "Pong"}
    elif tag == 1:
        return {"type": "Config", "raw": rest.hex()}
    elif tag == 2:
        rssi = struct.unpack_from("<h", rest, 0)[0]
        snr = struct.unpack_from("<h", rest, 2)[0]
        plen = struct.unpack_from("<H", rest, 4)[0]
        payload = rest[6 : 6 + plen]
        return {"type": "RxPacket", "rssi": rssi, "snr": snr, "payload": payload}
    elif tag == 3:
        return {"type": "TxDone"}
    elif tag == 4:
        return {"type": "Ok"}
    elif tag == 5:
        code = rest[0] if rest else -1
        return {"type": "Error", "code": code}
    else:
        return {"type": f"Unknown({tag})", "raw": rest.hex()}


def send_cmd(ser: serial.Serial, cmd: dict, label: str = "") -> dict | None:
    payload = encode_command(cmd)
    frame = cobs_frame(payload)
    if label:
        print(f"  {DIM}>>> {label}{RST}")
    ser.write(frame)
    ser.flush()
    for _ in range(50):
        resp_data = read_frame(ser)
        if resp_data is None:
            return None
        resp = decode_response(resp_data)
        if resp["type"] == "RxPacket":
            continue
        return resp
    return None


def transmit(ser: serial.Serial, packet: bytes, label: str = "TX"):
    resp = send_cmd(ser, {"type": "Transmit", "payload": packet}, label=label)
    if resp is None:
        print(f"  {RED}TX failed: no response{RST}")
    elif resp["type"] == "Error":
        print(f"  {RED}TX error: {resp}{RST}")


# ── MeshCore packet parsing ──────────────────────────────────────


def parse_header_and_path(packet: bytes):
    """Parse MeshCore header + path.

    Returns (payload_type, route_type, pos, payload, path_hops, hash_size) or None.
    """
    if len(packet) < 3:
        return None

    header = packet[0]
    route_type = header & 0x03
    payload_type = (header >> 2) & 0x0F
    payload_ver = (header >> 6) & 0x03
    if payload_ver != 0:
        return None

    has_tc = route_type in (0, 3)

    for skip_tc in ([True, False] if has_tc else [False]):
        pos = 5 if skip_tc else 1
        if pos >= len(packet):
            continue

        path_len_byte = packet[pos]
        pos += 1
        hash_size_code = path_len_byte >> 6
        if hash_size_code == 3:
            continue
        hash_size = hash_size_code + 1
        hop_count = path_len_byte & 0x3F
        path_bytes = hop_count * hash_size
        if path_bytes > 64 or pos + path_bytes > len(packet):
            continue

        hops = []
        for i in range(hop_count):
            hops.append(packet[pos + i * hash_size : pos + (i + 1) * hash_size])
        pos += path_bytes

        payload = packet[pos:]
        if payload and len(payload) <= 184:
            return payload_type, route_type, pos, payload, hops, hash_size

    return None


# ── Packet construction ──────────────────────────────────────────

_RT_NAMES = {0: "tflood", 1: "flood", 2: "direct", 3: "tdirect"}


def _build_routed_packet(
    payload_type: int,
    payload: bytes,
    route: tuple[list[bytes], int] | None,
) -> tuple[bytes, str]:
    """Build a packet with the given route. Returns (packet, route_description)."""
    if route is not None:
        hops, hash_size = route
        hash_size_code = hash_size - 1
        path_len_byte = (hash_size_code << 6) | (len(hops) & 0x3F)
        path_data = b"".join(hops)
        header = bytes([(payload_type << 2) | 2])  # DIRECT
        return header + bytes([path_len_byte]) + path_data + payload, "direct"
    else:
        header = bytes([(payload_type << 2) | 1])  # FLOOD
        path_len = bytes([0x40])  # 0 hops, 2-byte hash mode
        return header + path_len + payload, "flood"


def _build_direct_zero_hop_packet(payload_type: int, payload: bytes) -> bytes:
    """Build a zero-hop direct packet (reaches only immediate neighbours)."""
    header = bytes([(payload_type << 2) | 2])  # DIRECT
    path_len = bytes([0x40])  # 0 hops, 2-byte hash mode
    return header + path_len + payload


# ── ANON_REQ (login) ─────────────────────────────────────────────


def build_login_packet(
    repeater_pubkey: bytes,
    password: str,
    route: tuple[list[bytes], int] | None,
) -> tuple[bytes, str]:
    """Build an ANON_REQ login packet for a repeater.

    Plaintext: timestamp(4) + password (UTF-8, no null terminator needed —
    encryption pads to 16-byte boundary, server reads until null/end).

    Returns (packet, route_description).
    """
    shared_secret = _ecdh_shared_secret(repeater_pubkey)

    # Repeater login plaintext: timestamp(4) + password bytes
    plaintext = struct.pack("<I", int(time.time()))
    plaintext += password[:15].encode("utf-8")

    mac_ct = _encrypt(shared_secret, plaintext)

    # ANON_REQ payload: dest_hash(1) + sender_pubkey(32) + mac(2) + ciphertext
    anon_payload = bytes([repeater_pubkey[0]]) + _pubkey_bytes + mac_ct

    return _build_routed_packet(0x07, anon_payload, route)


# ── Telemetry REQUEST ─────────────────────────────────────────────


def build_telemetry_request(
    repeater_pubkey: bytes,
    route: tuple[list[bytes], int] | None,
) -> tuple[bytes, str]:
    """Build a REQ packet with protocol_code=GET_TELEMETRY_DATA.

    Plaintext: timestamp(4) + protocol_code(1) + inverse_perm_mask(1)
    We want base + environment (battery + temp), skip location.

    Returns (packet, route_description).
    """
    shared_secret = _ecdh_shared_secret(repeater_pubkey)

    # inverse perm mask: skip location only
    inv_mask = TELEM_PERM_LOCATION

    plaintext = struct.pack("<I", int(time.time()))
    plaintext += bytes([REQ_TYPE_GET_TELEMETRY_DATA, inv_mask])

    mac_ct = _encrypt(shared_secret, plaintext)

    # REQUEST payload: dest_hash(1) + src_hash(1) + mac(2) + ciphertext
    req_payload = bytes([repeater_pubkey[0], _my_hash()]) + mac_ct

    return _build_routed_packet(0x00, req_payload, route)


# ── CayenneLPP decoder ───────────────────────────────────────────

# Type ID → (name, data_size_bytes, scale_divisor)
# Per ElectronicCats/CayenneLPP library used by MeshCore firmware
CAYENNE_TYPES: dict[int, tuple[str, int, float]] = {
    0x00: ("digital_in", 1, 1),
    0x01: ("digital_out", 1, 1),
    0x02: ("analog_in", 2, 100),        # 0.01V
    0x03: ("analog_out", 2, 100),       # 0.01V (older firmware uses this for battery)
    0x65: ("illuminance", 2, 1),
    0x66: ("presence", 1, 1),
    0x67: ("temperature", 2, 10),       # 0.1°C, signed
    0x68: ("humidity", 1, 2),           # 0.5%
    0x71: ("accelerometer", 6, 1000),   # 0.001G per axis
    0x73: ("barometer", 2, 10),         # 0.1 hPa
    0x74: ("voltage", 2, 100),          # 0.01V — MeshCore addVoltage()
    0x75: ("current", 2, 1000),         # 0.001A — MeshCore addCurrent()
    0x76: ("percentage", 1, 1),
    0x80: ("power", 2, 1),             # 1W — MeshCore addPower()
    0x82: ("distance", 4, 1000),       # 0.001m
    0x86: ("gps", 9, 1),
    0x88: ("gps", 9, 1),
}


def decode_cayenne_lpp(data: bytes) -> list[dict]:
    """Decode CayenneLPP payload. Returns list of sensor readings."""
    sensors = []
    pos = 0
    while pos < len(data):
        if pos + 2 > len(data):
            break
        channel = data[pos]
        type_id = data[pos + 1]
        pos += 2

        type_info = CAYENNE_TYPES.get(type_id)
        if type_info is None:
            # Unknown type — can't determine size, stop parsing
            break

        name, size, divisor = type_info
        if pos + size > len(data):
            break

        raw = data[pos : pos + size]
        pos += size

        # Decode value (big-endian per CayenneLPP spec)
        signed = name in ("temperature", "analog_in", "analog_out", "voltage", "current")
        val_raw = int.from_bytes(raw, "big", signed=signed) if size > 1 else raw[0]
        value = val_raw / divisor

        UNITS = {
            "temperature": "°C", "humidity": "%", "barometer": "hPa",
            "voltage": "V", "analog_in": "V", "analog_out": "V",
            "current": "A", "power": "W", "distance": "m",
            "illuminance": "lux", "percentage": "%",
        }
        sensors.append({
            "channel": channel, "type": name,
            "value": value, "unit": UNITS.get(name, ""),
        })

    return sensors


# ── Response waiting ──────────────────────────────────────────────


def wait_for_response(
    ser: serial.Serial,
    repeater_pubkey: bytes,
    expected_types: set[int],
    timeout: float,
) -> tuple[dict | None, list[bytes], int]:
    """Wait for a MeshCore response addressed to us from the repeater.

    Returns (parsed_info, path_hops, hash_size) or (None, [], 0).
    parsed_info depends on payload type.
    """
    pk_hex = repeater_pubkey.hex()
    shared_secret = _ecdh_shared_secret(repeater_pubkey)
    dest_hash = repeater_pubkey[0]
    deadline = time.monotonic() + timeout
    old_timeout = ser.timeout
    ser.timeout = 1

    try:
        while time.monotonic() < deadline:
            data = read_frame(ser)
            if data is None:
                continue

            resp = decode_response(data)
            if resp["type"] != "RxPacket":
                continue

            packet = resp["payload"]
            parsed = parse_header_and_path(packet)
            if parsed is None:
                continue

            payload_type, route_type, pos, raw_payload, path_hops, hash_size = parsed

            if payload_type not in expected_types:
                continue

            # ── PATH (0x08) — responses routed back via PATH ──
            if payload_type == 0x08:
                if len(raw_payload) < 20:
                    continue
                dst = raw_payload[0]
                src = raw_payload[1]
                if dst != _my_hash():
                    continue
                if src != dest_hash:
                    continue

                mac_bytes = raw_payload[2:4]
                ciphertext = raw_payload[4:]
                plaintext = _verify_and_decrypt(shared_secret, mac_bytes, ciphertext)
                if plaintext is None:
                    continue

                # PATH inner: path_len(1) + path_data + extra_type(1) + extra_data
                inner_path_len_byte = plaintext[0]
                inner_hash_size = (inner_path_len_byte >> 6) + 1
                inner_hop_count = inner_path_len_byte & 0x3F
                inner_path_bytes = inner_hop_count * inner_hash_size
                ipos = 1 + inner_path_bytes

                if ipos < len(plaintext):
                    extra_type = plaintext[ipos]
                    extra_data = plaintext[ipos + 1:]
                else:
                    extra_type = 0xFF
                    extra_data = b""

                # Learn route from inner path
                if inner_hop_count > 0:
                    inner_hops = []
                    for i in range(inner_hop_count):
                        inner_hops.append(plaintext[1 + i * inner_hash_size : 1 + (i + 1) * inner_hash_size])
                    _learn_route(pk_hex, inner_hops, inner_hash_size)
                    _save_state()

                if extra_type != 0x01 or len(extra_data) < 4:
                    continue

                timestamp = struct.unpack_from("<I", extra_data, 0)[0]

                # Detect login responses by their structure:
                # Login: ts(4) + rc(1=0x00|0x80) + legacy(1) + admin(1) + perms(1) + random(4) + fw_ver(1)
                is_login_response = (
                    len(extra_data) >= 13
                    and extra_data[4] in (0x00, 0x80)
                    and extra_data[12] in (0x01, 0x02, 0x03)
                )

                if is_login_response:
                    if 0x01 in expected_types:
                        # Waiting for telemetry — skip this stale login response
                        continue  # skip stale login response
                    response_code = extra_data[4]
                    is_admin = extra_data[6] if len(extra_data) > 6 else 0
                    return {
                        "type": "login_response",
                        "response_code": response_code,
                        "is_admin": bool(is_admin),
                        "timestamp": timestamp,
                    }, path_hops, hash_size

                # Telemetry response: ts(4) + CayenneLPP (no response_code)
                if 0x01 in expected_types:
                    lpp_data = extra_data[4:]
                    while lpp_data and lpp_data[-1] == 0:
                        lpp_data = lpp_data[:-1]
                    sensors = decode_cayenne_lpp(lpp_data) if lpp_data else []
                    return {
                        "type": "telemetry",
                        "reflected_timestamp": timestamp,
                        "sensors": sensors,
                        "raw_hex": extra_data.hex(),
                    }, path_hops, hash_size

                continue

            # ── RESPONSE (0x01) — telemetry data ──
            if payload_type == 0x01:
                if len(raw_payload) < 20:
                    continue
                dst = raw_payload[0]
                src = raw_payload[1]
                if dst != _my_hash():
                    continue
                if src != dest_hash:
                    continue

                mac_bytes = raw_payload[2:4]
                ciphertext = raw_payload[4:]
                plaintext = _verify_and_decrypt(shared_secret, mac_bytes, ciphertext)
                if plaintext is None:
                    continue

                # Telemetry response: timestamp(4) + CayenneLPP (no response_code)
                if len(plaintext) < 4:
                    continue

                reflected_ts = struct.unpack_from("<I", plaintext, 0)[0]
                lpp_data = plaintext[4:]

                # Strip trailing zero padding
                while lpp_data and lpp_data[-1] == 0:
                    lpp_data = lpp_data[:-1]

                sensors = decode_cayenne_lpp(lpp_data) if lpp_data else []

                return {
                    "type": "telemetry",
                    "reflected_timestamp": reflected_ts,
                    "sensors": sensors,
                    "raw_hex": plaintext.hex(),
                }, path_hops, hash_size

    finally:
        ser.timeout = old_timeout

    return None, [], 0


# ── Route escalation ─────────────────────────────────────────────


def _route_strategies(pk_hex: str) -> list[tuple[tuple[list[bytes], int] | None, str]]:
    """Return route strategies in escalation order.

    a) last known route  b) zero-hop direct  c) flood
    """
    strategies = []

    # a) Last known route
    known = _get_route(pk_hex)
    if known is not None:
        strategies.append((known, "last-known"))

    # b) Zero-hop direct (immediate neighbours only — no flooding)
    strategies.append(("zero-hop", "zero-hop"))

    # c) Flood (only as last resort)
    strategies.append((None, "flood"))

    return strategies


# ── Poll one repeater ─────────────────────────────────────────────


def poll_repeater(ser: serial.Serial, repeater: dict) -> dict | None:
    """Login to repeater, fetch telemetry. Returns telemetry dict or None."""
    name = repeater["name"]
    pubkey = bytes.fromhex(repeater["pubkey"])
    password = repeater["password"]
    pk_hex = repeater["pubkey"]

    print(f"\n  {BCYN}── {name} ──{RST}")

    strategies = _route_strategies(pk_hex)

    # Step 1: Login with route escalation + flood retries
    login_ok = False
    for route_val, route_desc in strategies:
        # Flood gets multiple attempts since it should always eventually work
        attempts = FLOOD_RETRIES if route_val is None else 1

        for attempt in range(attempts):
            if route_val == "zero-hop":
                shared_secret = _ecdh_shared_secret(pubkey)
                plaintext = struct.pack("<I", int(time.time()))
                plaintext += password[:15].encode("utf-8")
                mac_ct = _encrypt(shared_secret, plaintext)
                anon_payload = bytes([pubkey[0]]) + _pubkey_bytes + mac_ct
                packet = _build_direct_zero_hop_packet(0x07, anon_payload)
                actual_desc = "zero-hop"
            else:
                packet, actual_desc = build_login_packet(pubkey, password, route_val)
                actual_desc = route_desc

            retry_label = f" #{attempt + 1}" if attempts > 1 and attempt > 0 else ""
            print(f"  {DIM}Login via {actual_desc}{retry_label}...{RST}", end="", flush=True)
            transmit(ser, packet, label=f"LOGIN({actual_desc})→{name}")
            time.sleep(TX_SETTLE)

            result, path_hops, hash_size = wait_for_response(
                ser, pubkey, {0x08}, LOGIN_TIMEOUT
            )

            if result is not None and result.get("response_code") in (0x00, 0x80):
                login_ok = True
                if path_hops:
                    _learn_route(pk_hex, path_hops, hash_size)
                    _save_state()
                    print(f" {GRN}OK{RST} {DIM}(learned {len(path_hops)}-hop route){RST}")
                else:
                    print(f" {GRN}OK{RST}")
                break
            elif result is not None:
                print(f" {RED}rejected (code=0x{result.get('response_code', -1):02x}){RST}")
                login_ok = False
                break  # Wrong password — don't retry
            else:
                print(f" {YEL}timeout{RST}")

        if login_ok or (result is not None and result.get("response_code") not in (0x00, 0x80)):
            break

    if not login_ok:
        print(f"  {RED}Login failed for {name}{RST}")
        return None

    # Step 2: Request telemetry with escalation (direct → flood with retries)
    telem_strategies = []
    known = _get_route(pk_hex)
    if known is not None:
        telem_strategies.append((known, "direct"))
    telem_strategies.append((None, "flood"))

    result = None
    for route, route_desc in telem_strategies:
        attempts = FLOOD_RETRIES if route is None else 1

        for attempt in range(attempts):
            packet, _ = build_telemetry_request(pubkey, route)
            retry_label = f" #{attempt + 1}" if attempts > 1 and attempt > 0 else ""
            print(f"  {DIM}Requesting telemetry via {route_desc}{retry_label}...{RST}", end="", flush=True)
            transmit(ser, packet, label=f"TELEM_REQ({route_desc})→{name}")
            time.sleep(TX_SETTLE)

            result, path_hops, hash_size = wait_for_response(
                ser, pubkey, {0x01, 0x08}, TELEM_TIMEOUT
            )

            if result is not None:
                if path_hops:
                    _learn_route(pk_hex, path_hops, hash_size)
                    _save_state()
                print(f" {GRN}OK{RST}")
                break
            else:
                print(f" {YEL}timeout{RST}")

        if result is not None:
            break
        # Clear stale route before escalating to next strategy
        _route_table.pop(pk_hex, None)

    if result is None:
        print(f"  {RED}Telemetry failed for {name}{RST}")
        return None

    # Display raw hex for debugging
    raw_hex = result.get("raw_hex", "")
    if raw_hex:
        print(f"    {DIM}raw: {raw_hex}{RST}")

    # Display parsed sensors — deduplicate by (channel, type), keep first
    # (external sensors are added before MCU fallback in firmware)
    sensors = result.get("sensors", [])
    seen = set()
    deduped = []
    for s in sensors:
        key = (s["channel"], s["type"])
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    if deduped:
        for s in deduped:
            stype = s["type"]
            val = s["value"]
            unit = s.get("unit", "")
            if stype == "temperature":
                f_val = val * 9 / 5 + 32
                print(f"    {BWHT}temperature{RST}: {val:.1f}°C / {f_val:.1f}°F")
            elif stype in ("voltage", "analog_in", "analog_out") and unit == "V":
                print(f"    {BWHT}voltage{RST}: {val:.2f}V")
            elif stype in ("digital_in", "digital_out"):
                state = "On" if val else "Off"
                print(f"    {DIM}digital {stype.split('_')[1]}{RST}: {state}")
            else:
                print(f"    {BWHT}{stype}{RST} ch{s['channel']}: {val:.2f}{unit}")

    return result


# ── ADVERT decoding ──────────────────────────────────────────────


def decode_advert(raw_payload: bytes) -> tuple[bytes, str, int] | None:
    """Decode and verify an ADVERT. Returns (pubkey, name, node_type) or None."""
    if len(raw_payload) < 100:
        return None

    pubkey = raw_payload[0:32]
    timestamp = raw_payload[32:36]
    signature = raw_payload[36:100]
    app_data = raw_payload[100:]

    try:
        verify_key = VerifyKey(pubkey)
        sign_msg = pubkey + timestamp + app_data
        verify_key.verify(sign_msg, signature)
    except Exception:
        return None

    name = ""
    node_type = 0
    if app_data:
        flags = app_data[0]
        node_type = flags & 0x0F
        pos = 1
        if flags & 0x10:  # has location
            pos += 8
        if flags & 0x20:  # feat1
            pos += 2
        if flags & 0x40:  # feat2
            pos += 2
        if flags & 0x80 and pos < len(app_data):  # has name
            name = app_data[pos:].decode("utf-8", errors="replace")

    return pubkey, name if name else pubkey.hex()[:8], node_type


def discover_pubkeys(ser: serial.Serial, wanted: list[dict]) -> int:
    """Listen for ADVERTs and match against repeaters missing pubkeys.

    Returns number of pubkeys discovered.
    """
    # Build a lookup: lowercase name → list of config entries wanting that name
    by_name: dict[str, list[dict]] = {}
    for r in wanted:
        by_name.setdefault(r["name"].lower(), []).append(r)

    found = 0
    total = len(wanted)
    print(f"\n  {BCYN}Waiting for ADVERTs from {total} repeater(s):{RST}")
    for r in wanted:
        print(f"    {CYN}{r['name']}{RST}")

    old_timeout = ser.timeout
    ser.timeout = 1

    try:
        while found < total:
            data = read_frame(ser)
            if data is None:
                continue

            resp = decode_response(data)
            if resp["type"] != "RxPacket":
                continue

            packet = resp["payload"]
            parsed = parse_header_and_path(packet)
            if parsed is None:
                continue

            payload_type, route_type, pos, raw_payload, path_hops, hash_size = parsed
            if payload_type != 0x04:  # not ADVERT
                continue

            result = decode_advert(raw_payload)
            if result is None:
                continue

            pubkey, adv_name, node_type = result
            pk_hex = pubkey.hex()

            # Match against wanted names (case-insensitive)
            matches = by_name.get(adv_name.lower(), [])
            if not matches:
                print(f"  {DIM}ADVERT {adv_name} (not in config){RST}")
                continue

            for r in matches:
                if r.get("pubkey"):
                    continue  # already discovered
                r["pubkey"] = pk_hex
                found += 1
                # Learn route from the ADVERT path too
                if path_hops:
                    _learn_route(pk_hex, path_hops, hash_size)
                print(
                    f"  {BGRN}Discovered {adv_name}{RST} "
                    f"{DIM}pubkey={pk_hex[:16]}... "
                    f"hash=0x{pubkey[0]:02x}{RST}"
                )

            if found >= total:
                break
    finally:
        ser.timeout = old_timeout

    return found


# ── Config ────────────────────────────────────────────────────────


def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        print(f"  {RED}Config not found: {CONFIG_FILE}{RST}")
        print(f"  {DIM}Create it with:{RST}")
        print(f"""
    {{
        "repeaters": [
            {{
                "name": "MyRepeater",
                "password": "guest123"
            }}
        ],
        "poll_interval_secs": 3600
    }}""")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    repeaters = config.get("repeaters", [])
    if not repeaters:
        print(f"  {RED}No repeaters configured in {CONFIG_FILE}{RST}")
        sys.exit(1)

    for r in repeaters:
        if "name" not in r or "password" not in r:
            print(f"  {RED}Repeater missing name or password: {r}{RST}")
            sys.exit(1)
        pk = r.get("pubkey", "")
        if pk and len(pk) != 64:
            print(f"  {RED}Invalid pubkey length for {r['name']}: expected 64 hex chars{RST}")
            sys.exit(1)

    return config


def save_config(config: dict):
    """Write config back to disk (atomic)."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        tmp.rename(CONFIG_FILE)
    except Exception as e:
        print(f"  {RED}Failed to save config: {e}{RST}")


def needs_discovery(config: dict) -> list[dict]:
    """Return repeaters that are missing their pubkey."""
    return [r for r in config["repeaters"] if not r.get("pubkey")]


# ── Main loop ─────────────────────────────────────────────────────


def _print_repeater_status(repeaters: list[dict]):
    for r in repeaters:
        pk = r.get("pubkey", "")
        if pk:
            route = _get_route(pk)
            route_str = f"{len(route[0])}-hop" if route else "none"
            print(f"    {CYN}{r['name']}{RST} {DIM}(hash=0x{bytes.fromhex(pk)[0]:02x} route={route_str}){RST}")
        else:
            print(f"    {CYN}{r['name']}{RST} {YEL}(pubkey unknown — will discover via ADVERT){RST}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MeshCore repeater telemetry monitor")
    parser.add_argument("--port", "-p", default=None, help="Serial port (auto-detect if omitted)")
    args = parser.parse_args()

    _init_identity()
    _load_state()
    config = load_config()

    repeaters = config["repeaters"]
    poll_interval = config.get("poll_interval_secs", DEFAULT_POLL_INTERVAL)

    print(f"\n  {BWHT}Telemetry Monitor{RST}")
    print(f"  {DIM}Repeaters: {len(repeaters)} | Poll interval: {poll_interval}s{RST}")
    _print_repeater_status(repeaters)

    port = args.port

    while True:
        try:
            print(f"  {DIM}Connecting...{RST}")
            ser = open_connection(port)
            print(f"  {GRN}Connected{RST}")

            send_cmd(ser, {"type": "Ping"}, "Ping")
            send_cmd(ser, {"type": "SetConfig", "config": RADIO_CONFIG}, "SetConfig")
            send_cmd(ser, {"type": "StartRx"}, "StartRx")

            # Discover any repeaters missing their pubkey
            missing = needs_discovery(config)
            if missing:
                found = discover_pubkeys(ser, missing)
                if found:
                    save_config(config)
                    _save_state()
                    print(f"  {BGRN}Saved {found} pubkey(s) to {CONFIG_FILE}{RST}")
                still_missing = needs_discovery(config)
                if still_missing:
                    names = ", ".join(r["name"] for r in still_missing)
                    print(f"  {YEL}Still waiting for: {names}{RST}")
                    print(f"  {DIM}Will retry discovery each poll cycle{RST}")

            while True:
                ts = time.strftime("%Y-%m-%d %H:%M:%S %Z")
                print(f"\n  {BWHT}═══ Poll cycle {ts} ═══{RST}")

                # Re-check for missing pubkeys each cycle
                missing = needs_discovery(config)
                if missing:
                    print(f"  {DIM}Listening for {len(missing)} missing ADVERT(s)...{RST}")
                    found = discover_pubkeys(ser, missing)
                    if found:
                        save_config(config)
                        _save_state()

                for repeater in repeaters:
                    if not repeater.get("pubkey"):
                        print(f"\n  {BCYN}── {repeater['name']} ──{RST}")
                        print(f"  {YEL}Skipping — pubkey not yet discovered{RST}")
                        continue
                    try:
                        poll_repeater(ser, repeater)
                    except (ConnectionError, OSError):
                        raise  # mux/serial disconnect — let outer loop reconnect
                    except Exception as e:
                        print(f"  {RED}Error polling {repeater['name']}: {e}{RST}")

                _save_state()

                next_poll = time.strftime(
                    "%H:%M:%S", time.localtime(time.time() + poll_interval)
                )
                print(f"\n  {DIM}Next poll at {next_poll} (sleeping {poll_interval}s){RST}")

                # Sleep in 1-second increments so Ctrl-C is responsive
                deadline = time.monotonic() + poll_interval
                while time.monotonic() < deadline:
                    time.sleep(1)

        except (serial.SerialException, ConnectionError, OSError) as e:
            print(f"\n  {RED}Disconnected: {e}{RST}")
            print(f"  {DIM}Reconnecting...{RST}")
            time.sleep(1)
        except KeyboardInterrupt:
            print()
            _save_state()
            try:
                ser.timeout = 2
                send_cmd(ser, {"type": "StopRx"}, "StopRx")
            except Exception:
                pass
            break


if __name__ == "__main__":
    main()
