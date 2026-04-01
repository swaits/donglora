#!/usr/bin/env python3
"""Generate MeshCore test vectors using Hypothesis (property-based testing)."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["hypothesis", "jsonschema"]
# ///

import argparse
import json
import struct
import sys
from pathlib import Path

from hypothesis import given, settings, HealthCheck, Phase
from hypothesis import strategies as st

CORPUS_DIR = Path(__file__).parent
OUT = CORPUS_DIR / "generated"
SCHEMA_PATH = CORPUS_DIR / "schema.json"

# MeshCore constants
MAX_PAYLOAD = 184
MAX_PATH_SIZE = 64
MAX_ADVERT_DATA_SIZE = 32
PUB_KEY_SIZE = 32
SIGNATURE_SIZE = 64

ROUTE_TYPES = {0: "tflood", 1: "flood", 2: "direct", 3: "tdirect"}
PAYLOAD_TYPES = {
    0: "REQ", 1: "RESPONSE", 2: "TXT_MSG", 3: "ACK", 4: "ADVERT",
    5: "GRP_TXT", 6: "GRP_DATA", 7: "ANON_REQ", 8: "PATH",
    9: "TRACE", 10: "MULTIPART", 11: "CONTROL", 15: "RAW_CUSTOM",
}
NODE_TYPES = {1: "chat", 2: "repeater", 3: "room", 4: "sensor"}


def mc_header(payload_type: int, route_type: int, ver: int = 0) -> int:
    return (ver << 6) | (payload_type << 2) | route_type


def path_len_byte(hop_count: int, hash_size: int) -> int:
    return ((hash_size - 1) << 6) | (hop_count & 0x3F)


# ── Hypothesis strategies ─────────────────────────────────────────

hash_sizes = st.sampled_from([1, 2, 3])
route_types_no_tc = st.sampled_from([1, 2])  # flood, direct (no transport codes)
route_types_all = st.sampled_from([0, 1, 2, 3])
payload_vers = st.sampled_from([0])  # only v0 is well-defined


@st.composite
def path_strategy(draw, hash_size=None):
    hs = hash_size or draw(hash_sizes)
    max_hops = min(63, MAX_PATH_SIZE // hs)
    hop_count = draw(st.integers(min_value=0, max_value=min(max_hops, 10)))
    hops = [draw(st.binary(min_size=hs, max_size=hs)) for _ in range(hop_count)]
    return hs, hops


@st.composite
def advert_appdata(draw):
    """Generate valid ADVERT app_data."""
    node_type = draw(st.sampled_from([1, 2, 3, 4]))
    has_loc = draw(st.booleans())
    has_name = draw(st.booleans())
    flags = node_type
    data = b""
    loc = None
    name = None

    if has_loc:
        flags |= 0x10
        lat = draw(st.integers(min_value=-90_000_000, max_value=90_000_000))
        lon = draw(st.integers(min_value=-180_000_000, max_value=180_000_000))
        data += struct.pack("<ii", lat, lon)
        loc = {"lat": round(lat / 1e6, 4), "lon": round(lon / 1e6, 4)}

    if has_name:
        flags |= 0x80
        # Generate ASCII names (to avoid UTF-8 scoring ambiguity in generated tests)
        name = draw(st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"),
                                   max_codepoint=127),
            min_size=1, max_size=20
        ))
        name_bytes = name.encode("ascii")
        data += name_bytes

    if len(data) + 1 > MAX_ADVERT_DATA_SIZE:
        data = data[:MAX_ADVERT_DATA_SIZE - 1]
        if name:
            name = data[8 if has_loc else 0:].decode("ascii", errors="replace")

    app_data = bytes([flags]) + data
    node_label = NODE_TYPES.get(node_type, f"0x{node_type:02x}")
    return app_data, {"flags": flags, "node_type": node_label, "location": loc, "name": name}


@st.composite
def valid_advert_packet(draw):
    """Generate a complete valid ADVERT packet with expected decode."""
    route_type = draw(route_types_no_tc)
    ver = draw(payload_vers)
    hs, hops = draw(path_strategy())
    pubkey = draw(st.binary(min_size=PUB_KEY_SIZE, max_size=PUB_KEY_SIZE))
    timestamp = draw(st.integers(min_value=0, max_value=0xFFFFFFFF))
    signature = draw(st.binary(min_size=SIGNATURE_SIZE, max_size=SIGNATURE_SIZE))
    app_data, advert_expected = draw(advert_appdata())

    hdr = bytes([mc_header(0x04, route_type, ver)])
    pl = bytes([path_len_byte(len(hops), hs)])
    path = b"".join(hops)
    payload = pubkey + struct.pack("<I", timestamp) + signature + app_data
    packet = hdr + pl + path + payload

    return packet, {
        "route_type": ROUTE_TYPES[route_type],
        "payload_type": "ADVERT",
        "payload_ver": ver,
        "transport_codes": None,
        "path": {"hash_size": hs, "hops": [h.hex() for h in hops]},
        "payload": {
            "pubkey_prefix": pubkey[:4].hex(),
            "timestamp": timestamp,
            "advert": advert_expected,
        }
    }


@st.composite
def valid_ack_packet(draw):
    route_type = draw(route_types_no_tc)
    hs, hops = draw(path_strategy())
    crc = draw(st.integers(min_value=0, max_value=0xFFFFFFFF))

    hdr = bytes([mc_header(0x03, route_type)])
    pl = bytes([path_len_byte(len(hops), hs)])
    path = b"".join(hops)
    packet = hdr + pl + path + struct.pack("<I", crc)

    return packet, {
        "route_type": ROUTE_TYPES[route_type],
        "payload_type": "ACK",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": hs, "hops": [h.hex() for h in hops]},
        "payload": {"ack_crc": crc}
    }


@st.composite
def valid_encrypted_peer_packet(draw):
    ptype = draw(st.sampled_from([0, 1, 2, 8]))  # REQ/RESPONSE/TXT_MSG/PATH
    route_type = draw(route_types_no_tc)
    hs, hops = draw(path_strategy())
    dst = draw(st.integers(min_value=0, max_value=255))
    src = draw(st.integers(min_value=0, max_value=255))
    mac = draw(st.binary(min_size=2, max_size=2))
    ct_len = draw(st.integers(min_value=16, max_value=64).filter(lambda n: n % 16 == 0))
    ct = draw(st.binary(min_size=ct_len, max_size=ct_len))

    hdr = bytes([mc_header(ptype, route_type)])
    pl = bytes([path_len_byte(len(hops), hs)])
    path = b"".join(hops)
    packet = hdr + pl + path + bytes([dst, src]) + mac + ct

    return packet, {
        "route_type": ROUTE_TYPES[route_type],
        "payload_type": PAYLOAD_TYPES[ptype],
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": hs, "hops": [h.hex() for h in hops]},
        "payload": {
            "dst": f"{dst:02x}",
            "src": f"{src:02x}",
            "mac": mac.hex(),
            "ciphertext_len": ct_len
        }
    }


@st.composite
def valid_group_packet(draw):
    ptype = draw(st.sampled_from([5, 6]))  # GRP_TXT/GRP_DATA
    route_type = draw(route_types_no_tc)
    hs, hops = draw(path_strategy())
    ch = draw(st.integers(min_value=0, max_value=255))
    mac = draw(st.binary(min_size=2, max_size=2))
    ct_len = draw(st.integers(min_value=16, max_value=64).filter(lambda n: n % 16 == 0))
    ct = draw(st.binary(min_size=ct_len, max_size=ct_len))

    hdr = bytes([mc_header(ptype, route_type)])
    pl = bytes([path_len_byte(len(hops), hs)])
    path = b"".join(hops)
    packet = hdr + pl + path + bytes([ch]) + mac + ct

    return packet, {
        "route_type": ROUTE_TYPES[route_type],
        "payload_type": PAYLOAD_TYPES[ptype],
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": hs, "hops": [h.hex() for h in hops]},
        "payload": {
            "channel_hash": f"{ch:02x}",
            "mac": mac.hex(),
            "ciphertext_len": ct_len
        }
    }


@st.composite
def invalid_packet(draw):
    """Generate an invalid MeshCore packet via mutation."""
    mutation = draw(st.sampled_from(["truncate", "bad_path_len", "random"]))

    if mutation == "truncate":
        # Valid packet truncated to random length
        pkt, _ = draw(valid_ack_packet())
        cut = draw(st.integers(min_value=0, max_value=max(0, len(pkt) - 2)))
        packet = pkt[:cut]
        if len(packet) < 3:
            error = "too_short"
        else:
            error = "bad_framing"
    elif mutation == "bad_path_len":
        # Header + impossible path_len
        route_type = draw(route_types_no_tc)
        ptype = draw(st.sampled_from(list(PAYLOAD_TYPES.keys())))
        hdr = bytes([mc_header(ptype, route_type)])
        # path_len claiming huge path
        # Use hash_size_code 3 (reserved, 0xC0-0xFF) or valid codes with huge counts
        bad_pl = draw(st.sampled_from([
            *range(0xC0, 0x100),  # reserved hash_size_code 3
            0x3F,  # 63 hops × 1 byte = 63 (valid encoding, will overflow data)
            0x60,  # 32 hops × 2 bytes = 64 (valid encoding, will overflow data)
            0x95,  # 21 hops × 3 bytes = 63 (valid encoding, will overflow data)
        ]))
        tail = draw(st.binary(min_size=1, max_size=20))
        packet = hdr + bytes([bad_pl]) + tail
        error = "bad_framing"
    else:  # random
        packet = draw(st.binary(min_size=3, max_size=50))
        error = "not_meshcore"

    header = packet[0] if packet else 0
    route_type = header & 0x03
    payload_type = (header >> 2) & 0x0F

    return packet, {
        "route_type": ROUTE_TYPES.get(route_type, f"rt{route_type}"),
        "payload_type": PAYLOAD_TYPES.get(payload_type, f"0x{payload_type:02x}"),
        "error": error if len(packet) < 2 else error
    }


# ── Generation ────────────────────────────────────────────────────

_counter = 0


def save_case(packet: bytes, expected: dict, valid: bool, prefix: str):
    global _counter
    _counter += 1
    ptype = expected["payload_type"].lower()
    name = f"{prefix}_{ptype}_{_counter:04d}"

    tags = [ptype, expected["route_type"]]
    if not valid:
        tags.append("invalid")
        if "error" in expected:
            tags.append(expected["error"])

    case = {
        "description": f"Generated {prefix}: {expected['payload_type']} {expected['route_type']}",
        "tags": tags,
        "packet_hex": packet.hex(),
        "valid": valid,
        "expected": expected,
    }

    # Validate against schema
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(case, schema)
    except jsonschema.ValidationError as e:
        print(f"  SKIP {name}: schema error: {e.message}")
        return

    (OUT / f"{name}.json").write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")


def generate(count: int):
    OUT.mkdir(exist_ok=True)

    # Clear previous generated files
    for f in OUT.glob("*.json"):
        f.unlink()

    global _counter
    _counter = 0

    strategies = [
        ("valid", valid_advert_packet(), True),
        ("valid", valid_ack_packet(), True),
        ("valid", valid_encrypted_peer_packet(), True),
        ("valid", valid_group_packet(), True),
        ("invalid", invalid_packet(), False),
    ]

    per_strategy = max(1, count // len(strategies))

    for prefix, strategy, valid in strategies:
        for i in range(per_strategy):
            example = strategy.example()
            packet, expected = example
            save_case(packet, expected, valid, prefix)

    total = len(list(OUT.glob("*.json")))
    print(f"Generated {total} test vectors in {OUT}/")


def main():
    parser = argparse.ArgumentParser(description="Generate MeshCore test vectors")
    parser.add_argument("--count", type=int, default=50, help="Total test cases to generate")
    args = parser.parse_args()
    generate(args.count)


if __name__ == "__main__":
    main()
