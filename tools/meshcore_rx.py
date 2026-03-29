#!/usr/bin/env python3
"""DongLoRa MeshCore receiver: decode and display MeshCore packets."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["cobs", "pyserial", "pycryptodome"]
# ///

import base64
import csv
import glob
import hashlib
import hmac
import json
import struct
import serial
import sys
import tempfile
import time
from cobs import cobs
from Crypto.Cipher import AES
from datetime import datetime, timezone
from pathlib import Path


# ── ANSI colors ───────────────────────────────────────────────────

RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GRN = "\033[32m"
YEL = "\033[33m"
BLU = "\033[34m"
MAG = "\033[35m"
CYN = "\033[36m"
WHT = "\033[37m"
BRED = "\033[1;31m"
BGRN = "\033[1;32m"
BYEL = "\033[1;33m"
BBLU = "\033[1;34m"
BMAG = "\033[1;35m"
BCYN = "\033[1;36m"
BWHT = "\033[1;37m"

TYPE_COLORS = {
    "ADVERT": BGRN,
    "ACK": DIM,
    "TXT_MSG": BCYN,
    "REQ": BYEL,
    "RESPONSE": BYEL,
    "GRP_TXT": BMAG,
    "GRP_DATA": BMAG,
    "ANON_REQ": YEL,
    "PATH": BBLU,
    "TRACE": BLU,
    "MULTIPART": YEL,
    "CONTROL": BLU,
    "RAW_CUSTOM": DIM,
}


def _rssi_color(rssi: int) -> str:
    if rssi >= -70:
        return GRN
    if rssi >= -100:
        return YEL
    return RED


def _snr_color(snr: int) -> str:
    if snr >= 0:
        return GRN
    if snr >= -10:
        return YEL
    return RED


# ── MeshCore channel crypto ────────────────────────────────────────

def _channel_secret_from_hashtag(name: str) -> bytes:
    """Derive 32-byte secret from a hashtag channel name (e.g., '#test')."""
    h = hashlib.sha256(name.encode()).digest()
    return h[:16] + b"\x00" * 16


def _channel_secret_from_psk(psk_b64: str) -> bytes:
    """Decode a base64 PSK into a 32-byte secret (16-byte key + 16 zero bytes)."""
    key = base64.b64decode(psk_b64)
    return key[:16] + b"\x00" * 16


def _channel_hash(secret: bytes) -> int:
    """Compute the 1-byte channel hash from a 32-byte secret."""
    # Hash over the key portion (16 bytes for hashtag/PSK channels)
    key_len = 16 if secret[16:] == b"\x00" * 16 else 32
    return hashlib.sha256(secret[:key_len]).digest()[0]


def _grp_verify_and_decrypt(secret: bytes, mac_bytes: bytes, ciphertext: bytes) -> bytes | None:
    """Verify MAC then decrypt a GRP_TXT/GRP_DATA payload. Returns plaintext or None."""
    if not ciphertext or len(ciphertext) % 16 != 0:
        return None
    # HMAC-SHA256 over ciphertext, truncated to 2 bytes
    key_len = 16 if secret[16:] == b"\x00" * 16 else 32
    computed_mac = hmac.new(secret[:key_len], ciphertext, hashlib.sha256).digest()[:2]
    if computed_mac != mac_bytes:
        return None
    # AES-128-ECB decrypt
    cipher = AES.new(secret[:16], AES.MODE_ECB)
    plaintext = b""
    for i in range(0, len(ciphertext), 16):
        plaintext += cipher.decrypt(ciphertext[i:i + 16])
    return plaintext


def _parse_grp_plaintext(plaintext: bytes) -> tuple[int, str] | None:
    """Parse decrypted GRP_TXT: timestamp(4) + flags(1) + text. Returns (timestamp, text)."""
    if len(plaintext) < 5:
        return None
    timestamp = struct.unpack_from("<I", plaintext, 0)[0]
    # flags_and_attempt at byte 4: (attempt & 3) | (txt_type << 2)
    text = plaintext[5:].split(b"\x00", 1)[0]  # null-terminated, strip zero padding
    return timestamp, text.decode("utf-8", errors="replace")


# Known channels: name → 32-byte secret
# Public channel has a hardcoded PSK; hashtag channels derive from name
_KNOWN_CHANNELS: dict[str, bytes] = {}

# channel_hash (1 byte) → list of (name, secret) for matching
_CHANNEL_BY_HASH: dict[int, list[tuple[str, bytes]]] = {}


def _register_channel(name: str, secret: bytes):
    _KNOWN_CHANNELS[name] = secret
    h = _channel_hash(secret)
    _CHANNEL_BY_HASH.setdefault(h, []).append((name, secret))


_CHANNELS_CSV = Path(__file__).parent / "channels.csv"


def _init_channels():
    """Load channels from channels.csv. Hashtag channels use key derivation;
    PSK channels (hashtag=False) use the raw key_hex."""
    if not _CHANNELS_CSV.is_file():
        print(f"{RED}channels.csv not found at {_CHANNELS_CSV}{RST}")
        return
    with open(_CHANNELS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            name = row["channel_name"]
            is_hashtag = row["hashtag"].strip().lower() == "true"
            key_hex = row["key_hex"].strip()
            if is_hashtag:
                secret = _channel_secret_from_hashtag(name)
            else:
                # PSK channel — raw 16-byte key
                secret = bytes.fromhex(key_hex) + b"\x00" * 16
            _register_channel(name, secret)


_init_channels()


# ── GRP_TXT transmit (encrypt + send) ─────────────────────────────

MAX_GRP_TEXT = 163  # max bytes for "SenderName: message" in a GRP_TXT


def _grp_encrypt(secret: bytes, sender: str, text: str) -> bytes:
    """Build an encrypted GRP_TXT payload (channel_hash + mac + ciphertext)."""
    ch = _channel_hash(secret)
    # Plaintext: timestamp(4) + flags(1) + "sender: text\0" + zero-pad
    plaintext = struct.pack("<I", int(time.time())) + b"\x00"
    plaintext += f"{sender}: {text}\x00".encode("utf-8")[:MAX_GRP_TEXT]
    pad_len = (16 - len(plaintext) % 16) % 16
    plaintext += b"\x00" * pad_len
    # AES-128-ECB encrypt
    cipher = AES.new(secret[:16], AES.MODE_ECB)
    ciphertext = b""
    for i in range(0, len(plaintext), 16):
        ciphertext += cipher.encrypt(plaintext[i:i + 16])
    # HMAC-SHA256 over ciphertext, truncated to 2 bytes
    key_len = 16 if secret[16:] == b"\x00" * 16 else 32
    mac = hmac.new(secret[:key_len], ciphertext, hashlib.sha256).digest()[:2]
    return bytes([ch]) + mac + ciphertext


def _grp_build_packet(channel_payload: bytes) -> bytes:
    """Wrap encrypted GRP_TXT payload into a full MeshCore packet."""
    header = bytes([0x15])  # GRP_TXT flood: (5 << 2) | 1
    path_len = bytes([0x40])  # 0 hops, 2-byte hash mode (hash_size_code=1 << 6)
    return header + path_len + channel_payload


def _grp_transmit(ser, channel_name: str, sender: str, text: str):
    """Encrypt and transmit a GRP_TXT message, then resume RX."""
    secret = _KNOWN_CHANNELS.get(channel_name)
    if secret is None:
        return
    payload = _grp_encrypt(secret, sender, text)
    packet = _grp_build_packet(payload)
    try:
        send_cmd(ser, {"type": "Transmit", "payload": packet},
                 f"TX GRP_TXT → {channel_name}")
    except Exception as e:
        print(f"  {RED}[TX failed: {e}]{RST}")
    # Always try to resume RX, even if TX failed
    try:
        send_cmd(ser, {"type": "StartRx"}, "StartRx (resume)")
    except Exception as e:
        print(f"  {RED}[StartRx failed: {e}]{RST}")


# ── Loop/collision aggregator ─────────────────────────────────────

REPORT_CHANNEL = "#watchman"
REPORT_SENDER = "Watchman"
REPORT_WINDOW = 60       # seconds — collect events before reporting
REPORT_COOLDOWN = 3600   # seconds — suppress repeat reports for same issue


def _nodes_for_hash(hash_hex: str, hash_size: int) -> int:
    """Count how many known nodes share this path hash."""
    return sum(1 for pk in _known_nodes if pk[:hash_size * 2] == hash_hex)


class LoopAggregator:
    def __init__(self):
        self._pending: list[dict] = []
        self._cooldown: dict[str, float] = {}
        self._window_start = time.monotonic()

    def record(self, dupes: dict[str, int], hash_size: int, all_hops: list[str]):
        """Record duplicate hops from one packet."""
        first_hop = all_hops[0] if all_hops else None
        self._pending.append({
            "dupes": dupes, "hash_size": hash_size, "hops": all_hops,
            "first_hop": first_hop,
        })

    def maybe_report(self, ser) -> bool:
        if not self._pending:
            self._window_start = time.monotonic()
            return False
        if time.monotonic() - self._window_start < REPORT_WINDOW:
            return False
        self._send_report(ser)
        return True

    def _send_report(self, ser):
        now = time.monotonic()
        messages: list[str] = []

        # Aggregate: (hash, hash_size) → {packets, relayers, senders}
        agg: dict[tuple[str, int], dict] = {}
        for ev in self._pending:
            for h, count in ev["dupes"].items():
                key = (h, ev["hash_size"])
                if key not in agg:
                    agg[key] = {"packets": 0, "relayers": set(), "senders": set()}
                agg[key]["packets"] += 1
                if ev["first_hop"]:
                    agg[key]["senders"].add(ev["first_hop"])
                for hop in ev["hops"]:
                    if hop != h:
                        agg[key]["relayers"].add(hop)

        for (h, hs), info in agg.items():
            issue_key = f"{h}:{hs}"
            if issue_key in self._cooldown and now - self._cooldown[issue_key] < REPORT_COOLDOWN:
                continue

            n_known = _nodes_for_hash(h, hs)
            pkts = info["packets"]
            senders = sorted(info["senders"])
            sender_str = ",".join(senders[:3]) if senders else "?"
            if len(senders) > 3:
                sender_str += f"+{len(senders) - 3}"
            relayer_str = ",".join(sorted(info["relayers"])[:3])
            if len(info["relayers"]) > 3:
                relayer_str += f"+{len(info['relayers']) - 3}"

            if n_known == 1:
                # Exactly one node matches → confirmed loop
                msg = f"Loop: {h} re-sent its own traffic ({pkts} pkt)."
                if relayer_str:
                    msg += f" Relayed by {relayer_str}."
                messages.append(msg)
            elif hs >= 2:
                if n_known > 1:
                    # 2B+ hash collision — rare, definitely a routing issue
                    msg = (f"Routing conflict: {n_known} nodes share {hs}B "
                           f"hash {h} ({pkts} pkt).")
                    messages.append(msg)
                else:
                    # 2B+ duplicate, unknown node → almost certainly a loop
                    msg = f"Probable loop: {h} appeared {pkts}x."
                    if relayer_str:
                        msg += f" Relayed by {relayer_str}."
                    messages.append(msg)
            else:
                # 1B hash — can't distinguish loop from collision
                if n_known > 1:
                    msg = (f"1B hash {h} duplicated in {pkts} pkt "
                           f"({n_known} known nodes share it). "
                           f"Sender {sender_str}: use 2B routing!")
                    messages.append(msg)
                else:
                    msg = (f"1B hash {h} duplicated in {pkts} pkt. "
                           f"Sender {sender_str}: use 2B routing to clarify!")
                    messages.append(msg)

            self._cooldown[issue_key] = now

        if not messages:
            self._reset()
            return

        full = " | ".join(messages)
        max_len = MAX_GRP_TEXT - len(REPORT_SENDER) - 2
        if len(full) > max_len:
            full = full[:max_len - 5] + "+more"

        print(f"  {BYEL}>>> Reporting to {REPORT_CHANNEL}: {full}{RST}")
        _grp_transmit(ser, REPORT_CHANNEL, REPORT_SENDER, full)
        self._reset()

    def _reset(self):
        self._pending.clear()
        self._window_start = time.monotonic()


_aggregator = LoopAggregator()


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
    if not buf:
        return None
    try:
        return cobs.decode(buf)
    except cobs.DecodeError:
        return None


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
    elif kind == "Transmit":
        out = varint(5)
        config = cmd.get("config")
        if config is None:
            out += b"\x00"  # Option::None
        else:
            out += b"\x01" + encode_radio_config(config)  # Option::Some
        payload = cmd["payload"]
        out += varint(len(payload)) + payload
        return out
    elif kind == "DisplayOn":
        return varint(6)
    elif kind == "DisplayOff":
        return varint(7)
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
    if not data:
        return {"type": "Empty"}
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


# ── MeshCore packet decoder ──────────────────────────────────────

ROUTE_NAMES = {0: "tflood", 1: "flood", 2: "direct", 3: "tdirect"}

PAYLOAD_NAMES = {
    0x00: "REQ",
    0x01: "RESPONSE",
    0x02: "TXT_MSG",
    0x03: "ACK",
    0x04: "ADVERT",
    0x05: "GRP_TXT",
    0x06: "GRP_DATA",
    0x07: "ANON_REQ",
    0x08: "PATH",
    0x09: "TRACE",
    0x0A: "MULTIPART",
    0x0B: "CONTROL",
    0x0F: "RAW_CUSTOM",
}

NODE_TYPES = {0x01: "chat", 0x02: "repeater", 0x03: "room", 0x04: "sensor"}

MAX_PATH_SIZE = 64

# ── Node registry (persistent, pruned at 12h) ────────────────────

ADVERT_MAX_AGE = 12 * 3600  # seconds
_ADVERT_FILE = Path(tempfile.gettempdir()) / "donglora_adverts.json"

# In-memory: pubkey_hex → {"name": str, "seen": float (unix timestamp)}
_known_nodes: dict[str, dict] = {}


def _load_adverts():
    """Load persisted adverts from disk, pruning stale entries."""
    global _known_nodes
    try:
        data = json.loads(_ADVERT_FILE.read_text())
        cutoff = time.time() - ADVERT_MAX_AGE
        _known_nodes = {k: v for k, v in data.items() if v.get("seen", 0) > cutoff}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        _known_nodes = {}


def _save_adverts():
    """Persist current adverts to disk (atomic write)."""
    try:
        tmp = _ADVERT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_known_nodes))
        tmp.rename(_ADVERT_FILE)
    except OSError:
        pass


def _lookup_hash(hash_hex: str, hash_size: int) -> list[str]:
    """Find node names whose pubkey prefix matches a path hash."""
    return [
        v["name"] for pk_hex, v in _known_nodes.items()
        if pk_hex[:hash_size * 2] == hash_hex
    ]


def _register_node(pubkey: bytes, name: str):
    """Register or update a node from an ADVERT."""
    pk_hex = pubkey.hex()
    _known_nodes[pk_hex] = {"name": name, "seen": time.time()}
    _save_adverts()


def _utf8_score(data: bytes) -> int:
    """Score how cleanly data decodes as UTF-8. Higher = more replacement chars."""
    return data.decode("utf-8", errors="replace").count("\ufffd")


def _best_name(candidates: list[bytes]) -> bytes:
    """Pick the candidate with the fewest UTF-8 replacement chars; longest wins ties."""
    return min(candidates, key=lambda d: (_utf8_score(d), -len(d)))


def _decode_advert_appdata(app_data: bytes) -> tuple[str, str]:
    """Decode advert app_data. Returns (display_string, node_name)."""
    if not app_data:
        return "", ""
    flags = app_data[0]
    node_type = flags & 0x0F
    node_label = NODE_TYPES.get(node_type, f"type={node_type}")
    parts = [f"{DIM}flags={RST}{flags:02x} {DIM}node={RST}{node_label}"]

    # Parse location if flagged and coords are valid
    off = 1
    loc_str = ""
    if flags & 0x10 and off + 8 <= len(app_data):
        lat_raw = struct.unpack_from("<i", app_data, off)[0]
        lon_raw = struct.unpack_from("<i", app_data, off + 4)[0]
        lat, lon = lat_raw / 1e6, lon_raw / 1e6
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            loc_str = f"{DIM}loc={RST}{lat:.4f},{lon:.4f}"
            off += 8

    # Build candidate name slices — try with/without feat fields
    off_with_feat = off
    if flags & 0x20 and off_with_feat + 2 <= len(app_data):
        off_with_feat += 2
    if flags & 0x40 and off_with_feat + 2 <= len(app_data):
        off_with_feat += 2

    name = ""
    if flags & 0x80:
        candidates = []
        if off_with_feat < len(app_data):
            candidates.append(app_data[off_with_feat:])
        if off < len(app_data) and off != off_with_feat:
            candidates.append(app_data[off:])
        # Also try raw name-at-byte-1 as a last resort (ignoring all flags)
        if 1 not in (off, off_with_feat) and 1 < len(app_data):
            candidates.append(app_data[1:])
        if candidates:
            best = _best_name(candidates)
            name = best.decode("utf-8", errors="replace")

    if loc_str:
        parts.append(loc_str)
    if name:
        parts.append(f"{BWHT}{name}{RST}")
    return " ".join(parts), name


LOOP_INDENT = " " * 38  # align under decoded packet text (after RSSI/SNR/len)


def _detect_loops(hops: list[str], hash_size: int) -> str | None:
    """Check for duplicate hops in a path. Returns a warning line or None."""
    if len(hops) < 2:
        return None
    counts: dict[str, int] = {}
    for h in hops:
        counts[h] = counts.get(h, 0) + 1
    dupes = {h: c for h, c in counts.items() if c > 1}
    if not dupes:
        return None

    # Feed the aggregator for deferred reporting
    _aggregator.record(dupes, hash_size, hops)

    parts = []
    for h, c in dupes.items():
        n_known = _nodes_for_hash(h, hash_size)
        if n_known == 1:
            # Exactly one node matches → confirmed loop
            parts.append(f"{BRED}{h} x{c} LOOP{RST}")
        elif hash_size >= 2:
            if n_known > 1:
                # 2B+ collision is rare and real
                parts.append(f"{BCYN}{h} x{c} COLLISION {DIM}({n_known} nodes){RST}")
            else:
                # 2B+ duplicate, unknown node → almost certainly a loop
                parts.append(f"{BRED}{h} x{c} LOOP{RST}")
        else:
            # 1B hash — ambiguous: could be loop or collision
            if n_known > 1:
                parts.append(f"{YEL}{h} x{c} {DIM}(loop or collision? {n_known} nodes share this 1B hash){RST}")
            else:
                parts.append(f"{YEL}{h} x{c} {DIM}(loop or collision? 1B hash){RST}")

    return f"{LOOP_INDENT}\u26a0 {', '.join(parts)}"


def _try_decode_body(data: bytes, pos: int, type_name: str, type_color: str,
                     payload_type: int, payload_ver: int, route_name: str,
                     tc_str: str) -> str | None:
    """Try to parse path + payload starting at pos. Returns decoded string or None."""
    if pos >= len(data):
        return None
    path_len_byte = data[pos]
    pos += 1
    hash_size = (path_len_byte >> 6) + 1
    hop_count = path_len_byte & 0x3F

    path_bytes = hop_count * hash_size
    if path_bytes > MAX_PATH_SIZE or pos + path_bytes > len(data):
        return None

    hops_str = ""
    loop_warn = ""
    hops: list[str] = []
    if hop_count > 0:
        for i in range(hop_count):
            h = data[pos + i * hash_size : pos + (i + 1) * hash_size]
            hops.append(h.hex())
        hops_str = f" {DIM}path=[{RST}{'>'.join(hops)}{DIM}]{RST}"
        warn = _detect_loops(hops, hash_size)
        if warn:
            loop_warn = f"\n{warn}"
    pos += path_bytes

    payload = data[pos:]
    prefix = f"{type_color}{type_name}{RST} {route_name}{tc_str}{hops_str}"

    if payload_type == 0x04:
        result = _decode_advert(prefix, payload)
    elif payload_type == 0x03:
        result = _decode_ack(prefix, payload)
    elif payload_type in (0x00, 0x01, 0x02, 0x08):
        result = _decode_encrypted_peer(prefix, type_name, payload)
    elif payload_type in (0x05, 0x06):
        result = _decode_encrypted_group(prefix, payload)
    elif payload_type == 0x07:
        result = _decode_anon_req(prefix, payload)
    elif payload_type == 0x09:
        result = _decode_trace(prefix, payload)
    elif payload_type == 0x0A:
        result = _decode_multipart(prefix, payload)
    elif payload_type == 0x0B:
        result = _decode_control(prefix, payload)
    else:
        result = f"{prefix} {DIM}{payload.hex()}{RST}" if payload else prefix

    return result + loop_warn


def decode_meshcore_packet(data: bytes) -> str:
    """Decode a MeshCore packet into a human-readable string."""
    if len(data) < 2:
        return f"{RED}<too short>{RST} {DIM}{data.hex()}{RST}"

    header = data[0]
    if header == 0xFF:
        return f"{DIM}<no-retransmit marker> {data[1:].hex()}{RST}"

    route_type = header & 0x03
    payload_type = (header >> 2) & 0x0F
    payload_ver = (header >> 6) & 0x03

    # MeshCore only implements PAYLOAD_VER_1 (0x00) — versions 1-3 are reserved
    # and rejected by real nodes. Packets with ver > 0 are noise or non-MeshCore.
    if payload_ver != 0:
        route_name = ROUTE_NAMES.get(route_type, f"rt{route_type}")
        type_name = PAYLOAD_NAMES.get(payload_type, f"0x{payload_type:02x}")
        return (f"{RED}<not meshcore>{RST} {DIM}hdr=0x{header:02x} "
                f"(ver={payload_ver} — only v0 exists) {data[1:].hex()}{RST}")

    route_name = ROUTE_NAMES.get(route_type, f"rt{route_type}")
    type_name = PAYLOAD_NAMES.get(payload_type, f"0x{payload_type:02x}")
    type_color = TYPE_COLORS.get(type_name, WHT)

    has_tc = route_type in (0, 3)

    # Try with transport codes first if indicated, fallback without
    if has_tc and len(data) >= 6:
        tc1, tc2 = struct.unpack_from("<HH", data, 1)
        tc_str = f" {DIM}tc={tc1:04x}:{tc2:04x}{RST}"
        result = _try_decode_body(data, 5, type_name, type_color,
                                  payload_type, payload_ver, route_name, tc_str)
        if result is not None:
            return result
        # TC parse failed — retry without (older firmware compatibility)
        result = _try_decode_body(data, 1, type_name, type_color,
                                  payload_type, payload_ver, route_name, "")
        if result is not None:
            return result
    else:
        result = _try_decode_body(data, 1, type_name, type_color,
                                  payload_type, payload_ver, route_name, "")
        if result is not None:
            return result

    # Both attempts failed — show what we know from the header
    return (f"{RED}<bad framing>{RST} {type_color}{type_name}{RST} "
            f"{route_name} {DIM}{data[1:].hex()}{RST}")


def _decode_advert(prefix: str, payload: bytes) -> str:
    if len(payload) < 100:
        return f"{prefix} {RED}<bad advert: {len(payload)}B, need >=100>{RST} {DIM}{payload.hex()}{RST}"
    pubkey = payload[0:32]
    timestamp = struct.unpack_from("<I", payload, 32)[0]
    app_data = payload[100:]
    try:
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        ts = f"epoch={timestamp}"
    app_str, name = _decode_advert_appdata(app_data)
    _register_node(pubkey, name)
    return f"{prefix} {DIM}pub={RST}{pubkey[:4].hex()}.. {DIM}ts={RST}{ts}Z {app_str}"


def _decode_ack(prefix: str, payload: bytes) -> str:
    if len(payload) < 4:
        return f"{prefix} {RED}<bad ack: {len(payload)}B>{RST} {DIM}{payload.hex()}{RST}"
    crc = struct.unpack_from("<I", payload, 0)[0]
    return f"{prefix} {DIM}crc={RST}0x{crc:08x}"


def _decode_encrypted_peer(prefix: str, type_name: str, payload: bytes) -> str:
    if len(payload) < 4:
        return f"{prefix} {RED}<bad {type_name}: {len(payload)}B>{RST} {DIM}{payload.hex()}{RST}"
    dst = payload[0]
    src = payload[1]
    mac = payload[2:4]
    ct_len = len(payload) - 4
    return f"{prefix} {DIM}dst={RST}{dst:02x} {DIM}src={RST}{src:02x} {DIM}mac={RST}{mac.hex()} {DIM}[{ct_len}B]{RST}"


def _decode_encrypted_group(prefix: str, payload: bytes) -> str:
    if len(payload) < 3:
        return f"{prefix} {RED}<bad group: {len(payload)}B>{RST} {DIM}{payload.hex()}{RST}"
    ch = payload[0]
    mac_bytes = payload[1:3]
    ciphertext = payload[3:]

    # Try to decrypt with known channels matching this hash
    candidates = _CHANNEL_BY_HASH.get(ch, [])
    for chan_name, secret in candidates:
        plaintext = _grp_verify_and_decrypt(secret, mac_bytes, ciphertext)
        if plaintext is not None:
            parsed = _parse_grp_plaintext(plaintext)
            if parsed:
                ts, text = parsed
                try:
                    ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
                except (OSError, OverflowError, ValueError):
                    ts_str = f"epoch={ts}"
                return (f"{prefix} {BGRN}{chan_name}{RST} "
                        f"{DIM}ts={RST}{ts_str}Z {BWHT}{text}{RST}")
            # MAC matched but plaintext unparseable
            return (f"{prefix} {BGRN}{chan_name}{RST} "
                    f"{DIM}[decrypted but unparseable]{RST}")

    # No known channel matched — show raw info
    return (f"{prefix} {DIM}ch={RST}{ch:02x} {DIM}mac={RST}{mac_bytes.hex()} "
            f"{DIM}[{len(ciphertext)}B]{RST}")


def _decode_anon_req(prefix: str, payload: bytes) -> str:
    if len(payload) < 35:
        return f"{prefix} {RED}<bad anon_req: {len(payload)}B>{RST} {DIM}{payload.hex()}{RST}"
    dst = payload[0]
    ephem_pub = payload[1:33]
    mac = payload[33:35]
    ct_len = len(payload) - 35
    return f"{prefix} {DIM}dst={RST}{dst:02x} {DIM}ephem={RST}{ephem_pub[:4].hex()}.. {DIM}mac={RST}{mac.hex()} {DIM}[{ct_len}B]{RST}"


def _decode_trace(prefix: str, payload: bytes) -> str:
    if len(payload) < 9:
        return f"{prefix} {RED}<bad trace: {len(payload)}B>{RST} {DIM}{payload.hex()}{RST}"
    tag = struct.unpack_from("<I", payload, 0)[0]
    flags = payload[8]
    trace_hash_size = (flags & 0x03) + 1
    trace_hashes = payload[9:]
    n_hashes = len(trace_hashes) // trace_hash_size if trace_hash_size else 0
    hops = []
    for i in range(n_hashes):
        h = trace_hashes[i * trace_hash_size : (i + 1) * trace_hash_size]
        hops.append(h.hex())
    hops_str = f" {DIM}trace=[{RST}{'>'.join(hops)}{DIM}]{RST}" if hops else ""
    return f"{prefix} {DIM}tag={RST}0x{tag:08x}{hops_str}"


def _decode_multipart(prefix: str, payload: bytes) -> str:
    if len(payload) < 1:
        return f"{prefix} {RED}<empty multipart>{RST}"
    remaining = (payload[0] >> 4) & 0x0F
    inner_type = payload[0] & 0x0F
    inner_name = PAYLOAD_NAMES.get(inner_type, f"0x{inner_type:02x}")
    return f"{prefix} {DIM}remaining={RST}{remaining} {DIM}inner={RST}{inner_name} {DIM}[{len(payload) - 1}B]{RST}"


def _decode_control(prefix: str, payload: bytes) -> str:
    if len(payload) < 1:
        return f"{prefix} {RED}<empty control>{RST}"
    sub_type = (payload[0] >> 4) & 0x0F
    sub_names = {0x8: "DISCOVER_REQ", 0x9: "DISCOVER_RESP"}
    sub_name = sub_names.get(sub_type, f"sub=0x{sub_type:x}")
    if sub_type == 0x8 and len(payload) >= 6:
        type_filter = payload[1]
        tag = struct.unpack_from("<I", payload, 2)[0]
        return f"{prefix} {sub_name} {DIM}filter={RST}0x{type_filter:02x} {DIM}tag={RST}0x{tag:08x}"
    elif sub_type == 0x9 and len(payload) >= 6:
        node_type = payload[0] & 0x0F
        snr_raw = struct.unpack_from("<b", payload, 1)[0]
        tag = struct.unpack_from("<I", payload, 2)[0]
        return f"{prefix} {sub_name} {DIM}node={RST}{NODE_TYPES.get(node_type, f'0x{node_type:02x}')} {DIM}snr={RST}{snr_raw / 4:.1f}dB {DIM}tag={RST}0x{tag:08x}"
    return f"{prefix} {sub_name} {DIM}{payload[1:].hex()}{RST}"


# ── Main ───────────────────────────────────────────────────────────


def send_cmd(ser: serial.Serial, cmd: dict, label: str) -> dict | None:
    payload = encode_command(cmd)
    frame = cobs_frame(payload)
    print(f"{DIM}>>>{RST} {label}")
    ser.write(frame)
    ser.flush()
    resp_data = read_frame(ser)
    if resp_data is None:
        print(f"    {YEL}timeout{RST}")
        return None
    resp = decode_response(resp_data)
    print(f"{DIM}<<<{RST} {resp}")
    return resp


RADIO_CONFIG = {
    "freq_hz": 910_525_000,
    "bw": 6,  # Khz62 = variant index 6
    "sf": 7,
    "cr": 5,  # CR 4/5 — denominator value
    "sync_word": 0x3444,
    "tx_power_dbm": 14,
}


def _format_rssi_snr(rssi: int, snr: int) -> str:
    rc = _rssi_color(rssi)
    sc = _snr_color(snr)
    line = f"{rc}RSSI:{rssi:4d}dBm{RST}  {sc}SNR:{snr:3d}dB{RST}"
    # Flag bogus dongle responses (SNR outside SX126x range -32..+32)
    if not (-32 <= snr <= 32):
        line += f"  {BRED}[bad SNR]{RST}"
    return line


def configure_and_listen(ser: serial.Serial):
    send_cmd(ser, {"type": "SetConfig", "config": RADIO_CONFIG}, "SetConfig 910.525/62.5k/SF7/CR4_5")
    send_cmd(ser, {"type": "StartRx"}, "StartRx")

    print(f"\n{BWHT}Listening for packets{RST} {DIM}(Ctrl+C to stop){RST}\n")
    ser.timeout = 1

    while True:
        try:
            _aggregator.maybe_report(ser)
        except Exception as e:
            print(f"  {RED}[report error: {e}]{RST}")

        data = read_frame(ser)
        if data is None:
            continue
        try:
            resp = decode_response(data)
            if resp["type"] == "RxPacket":
                payload = resp["payload"]
                decoded = decode_meshcore_packet(payload)
                rssi_snr = _format_rssi_snr(resp["rssi"], resp["snr"])
                print(
                    f"  {rssi_snr}  "
                    f"{DIM}len:{len(payload):3d}{RST}  "
                    f"{decoded}"
                )
            else:
                print(f"  {DIM}{resp}{RST}")
        except Exception as e:
            print(f"  {RED}[decode error: {e}] raw={data.hex()}{RST}")


def main():
    _load_adverts()
    n = len(_known_nodes)
    if n:
        print(f"{DIM}Loaded {n} known node(s) from {_ADVERT_FILE}{RST}")

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
            print(f"\n{RED}Disconnected: {e}{RST}")
            print("Will reconnect when device reappears...")
            port = None
            time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{DIM}Stopping...{RST}")
            try:
                ser.timeout = 2
                send_cmd(ser, {"type": "StopRx"}, "StopRx")
            except Exception:
                pass
            break


if __name__ == "__main__":
    main()
