#!/usr/bin/env python3
"""Build hand-crafted MeshCore test vectors as individual JSON files."""
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import json
import os
import struct
from pathlib import Path

OUT = Path(__file__).parent / "hand"
OUT.mkdir(exist_ok=True)


def write_case(name: str, case: dict):
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")
    print(f"  {path.name}")


# ── Packet building helpers ───────────────────────────────────────

def mc_header(payload_type: int, route_type: int, ver: int = 0) -> int:
    return (ver << 6) | (payload_type << 2) | route_type


def path_len_byte(hop_count: int, hash_size: int) -> int:
    return ((hash_size - 1) << 6) | (hop_count & 0x3F)


DUMMY_PUBKEY = bytes(range(32))
DUMMY_SIG = bytes(64)
TS_2026 = struct.pack("<I", 1774600000)  # ~2026-03-24


def advert_packet(app_data: bytes, route_type: int = 1,
                  path_hops: list[bytes] | None = None,
                  hash_size: int = 1, pubkey: bytes = DUMMY_PUBKEY,
                  timestamp: bytes = TS_2026) -> bytes:
    hdr = bytes([mc_header(0x04, route_type)])
    hops = path_hops or []
    pl = bytes([path_len_byte(len(hops), hash_size)])
    path = b"".join(hops)
    payload = pubkey + timestamp + DUMMY_SIG + app_data
    return hdr + pl + path + payload


def peer_packet(payload_type: int, route_type: int, dst: int, src: int,
                mac: bytes, ciphertext: bytes,
                path_hops: list[bytes] | None = None,
                hash_size: int = 1, tc: tuple[int, int] | None = None) -> bytes:
    hdr = bytes([mc_header(payload_type, route_type)])
    hops = path_hops or []
    pl_byte = bytes([path_len_byte(len(hops), hash_size)])
    path = b"".join(hops)
    body = bytes([dst, src]) + mac + ciphertext
    tc_bytes = b""
    if tc is not None:
        tc_bytes = struct.pack("<HH", tc[0], tc[1])
    return hdr + tc_bytes + pl_byte + path + body


def ack_packet(crc: int, route_type: int = 1,
               path_hops: list[bytes] | None = None,
               hash_size: int = 1) -> bytes:
    hdr = bytes([mc_header(0x03, route_type)])
    hops = path_hops or []
    pl_byte = bytes([path_len_byte(len(hops), hash_size)])
    path = b"".join(hops)
    return hdr + pl_byte + path + struct.pack("<I", crc)


def group_packet(payload_type: int, ch_hash: int, mac: bytes,
                 ciphertext: bytes, route_type: int = 1,
                 path_hops: list[bytes] | None = None,
                 hash_size: int = 1) -> bytes:
    hdr = bytes([mc_header(payload_type, route_type)])
    hops = path_hops or []
    pl_byte = bytes([path_len_byte(len(hops), hash_size)])
    path = b"".join(hops)
    return hdr + pl_byte + path + bytes([ch_hash]) + mac + ciphertext


def anon_req_packet(dst: int, ephem_pub: bytes, mac: bytes, ciphertext: bytes,
                    route_type: int = 1, path_hops: list[bytes] | None = None,
                    hash_size: int = 1) -> bytes:
    hdr = bytes([mc_header(0x07, route_type)])
    hops = path_hops or []
    pl_byte = bytes([path_len_byte(len(hops), hash_size)])
    path = b"".join(hops)
    return hdr + pl_byte + path + bytes([dst]) + ephem_pub + mac + ciphertext


def trace_packet(tag: int, auth_code: int, flags: int,
                 trace_hashes: bytes = b"",
                 route_type: int = 1,
                 path_hops: list[bytes] | None = None,
                 hash_size: int = 1) -> bytes:
    hdr = bytes([mc_header(0x09, route_type)])
    hops = path_hops or []
    pl_byte = bytes([path_len_byte(len(hops), hash_size)])
    path = b"".join(hops)
    payload = struct.pack("<II", tag, auth_code) + bytes([flags]) + trace_hashes
    return hdr + pl_byte + path + payload


def multipart_packet(remaining: int, inner_type: int, inner_payload: bytes,
                     route_type: int = 1) -> bytes:
    hdr = bytes([mc_header(0x0A, route_type)])
    pl_byte = bytes([path_len_byte(0, 1)])
    control = bytes([(remaining << 4) | (inner_type & 0x0F)])
    return hdr + pl_byte + control + inner_payload


def control_packet(flags_byte: int, payload: bytes,
                   route_type: int = 1) -> bytes:
    hdr = bytes([mc_header(0x0B, route_type)])
    pl_byte = bytes([path_len_byte(0, 1)])
    return hdr + pl_byte + bytes([flags_byte]) + payload


# ── Test cases ────────────────────────────────────────────────────

print("Building hand-crafted test vectors...")

# ADVERT: basic chat node with name
write_case("advert_basic", {
    "description": "ADVERT flood, chat node with simple ASCII name",
    "tags": ["advert", "flood", "name", "chat"],
    "packet_hex": advert_packet(bytes([0x81]) + b"TestNode").hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": {
                "flags": 0x81,
                "node_type": "chat",
                "location": None,
                "name": "TestNode"
            }
        }
    }
})

# ADVERT: repeater with valid GPS location + name
write_case("advert_location", {
    "description": "ADVERT flood, repeater with valid GPS coords and name",
    "tags": ["advert", "flood", "location", "repeater"],
    "packet_hex": advert_packet(
        bytes([0x92])
        + struct.pack("<i", 37774900) + struct.pack("<i", -122419400)
        + b"HilltopRptr"
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": {
                "flags": 0x92,
                "node_type": "repeater",
                "location": {"lat": 37.7749, "lon": -122.4194},
                "name": "HilltopRptr"
            }
        }
    }
})

# ADVERT: emoji name (multi-byte UTF-8)
emoji_name = "\U0001f985 Raptor"  # 🦅 Raptor
write_case("advert_emoji_name", {
    "description": "ADVERT flood, chat node with emoji in name (multi-byte UTF-8)",
    "tags": ["advert", "flood", "emoji", "name", "utf8"],
    "packet_hex": advert_packet(bytes([0x81]) + emoji_name.encode()).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": {
                "flags": 0x81,
                "node_type": "chat",
                "location": None,
                "name": emoji_name
            }
        }
    }
})

# ADVERT: feat flags set but data is actually name (scoring test)
write_case("advert_feat_flags_as_name", {
    "description": "ADVERT flood, feat1+feat2 bits set but bytes are actually the name",
    "tags": ["advert", "flood", "feat", "scoring", "emoji"],
    "packet_hex": advert_packet(
        bytes([0xe1]) + "\U0001f3d4\ufe0f MtnNode".encode()
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": {
                "flags": 0xe1,
                "node_type": "chat",
                "location": None,
                "name": "\U0001f3d4\ufe0f MtnNode"
            }
        }
    }
})

# ADVERT: no app_data (bare 100-byte advert)
write_case("advert_no_appdata", {
    "description": "ADVERT flood, bare minimum (no app_data)",
    "tags": ["advert", "flood", "minimal"],
    "packet_hex": advert_packet(b"").hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": None
        }
    }
})

# ADVERT: sensor node type
write_case("advert_sensor", {
    "description": "ADVERT flood, sensor node type",
    "tags": ["advert", "flood", "sensor"],
    "packet_hex": advert_packet(bytes([0x84]) + b"TempSensor").hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": {
                "flags": 0x84,
                "node_type": "sensor",
                "location": None,
                "name": "TempSensor"
            }
        }
    }
})

# ADVERT: with path (4 hops, 1-byte hash)
write_case("advert_with_path", {
    "description": "ADVERT flood, 4 hops with 1-byte hashes",
    "tags": ["advert", "flood", "path"],
    "packet_hex": advert_packet(
        bytes([0x81]) + b"RelayedNode",
        path_hops=[b"\x2a", b"\x3d", b"\x35", b"\xed"]
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": ["2a", "3d", "35", "ed"]},
        "payload": {
            "pubkey_prefix": DUMMY_PUBKEY[:4].hex(),
            "timestamp": 1774600000,
            "advert": {
                "flags": 0x81,
                "node_type": "chat",
                "location": None,
                "name": "RelayedNode"
            }
        }
    }
})

# ACK: basic
write_case("ack_basic", {
    "description": "ACK flood, simple acknowledgment",
    "tags": ["ack", "flood"],
    "packet_hex": ack_packet(0xDEADBEEF).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ACK",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {"ack_crc": 0xDEADBEEF}
    }
})

# ACK: with 1-byte hash path
write_case("ack_with_path", {
    "description": "ACK flood, 2 hops with 1-byte hashes",
    "tags": ["ack", "flood", "path"],
    "packet_hex": ack_packet(
        0x008DC29F, path_hops=[b"\xd1", b"\xac"]
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "ACK",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": ["d1", "ac"]},
        "payload": {"ack_crc": 0x008DC29F}
    }
})

# TXT_MSG: direct, 2-byte hashes
write_case("txt_msg_direct_2b_hash", {
    "description": "TXT_MSG direct, 2-byte hashes, 2 hops",
    "tags": ["txt_msg", "direct", "2byte_hash", "encrypted"],
    "packet_hex": peer_packet(
        0x02, 2, 0x5b, 0x43, b"\xab\xcd", bytes(48),
        path_hops=[b"\xac\x98", b"\xd1\x4d"], hash_size=2
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "direct",
        "payload_type": "TXT_MSG",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 2, "hops": ["ac98", "d14d"]},
        "payload": {"dst": "5b", "src": "43", "mac": "abcd", "ciphertext_len": 48}
    }
})

# TXT_MSG: flood with loops (duplicate hops)
write_case("txt_msg_flood_with_loops", {
    "description": "TXT_MSG flood with routing loop (ac98 appears 3x)",
    "tags": ["txt_msg", "flood", "loop", "2byte_hash"],
    "packet_hex": peer_packet(
        0x02, 1, 0x5b, 0x43, b"\xab\xcd", bytes(32),
        path_hops=[b"\xac\x98", b"\xd1\x4d", b"\xac\x98", b"\xff\x01", b"\xac\x98"],
        hash_size=2
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "TXT_MSG",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 2, "hops": ["ac98", "d14d", "ac98", "ff01", "ac98"]},
        "payload": {"dst": "5b", "src": "43", "mac": "abcd", "ciphertext_len": 32}
    }
})

# REQ: with transport codes (transport direct)
write_case("req_transport_direct", {
    "description": "REQ transport-direct with transport codes and 1-byte path",
    "tags": ["req", "tdirect", "transport_codes", "encrypted"],
    "packet_hex": peer_packet(
        0x00, 3, 0xa1, 0xb2, b"\xef\x01", bytes(32),
        path_hops=[b"\xcc", b"\xdd"], hash_size=1,
        tc=(0x1234, 0x5678)
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "tdirect",
        "payload_type": "REQ",
        "payload_ver": 0,
        "transport_codes": {"tc1": 0x1234, "tc2": 0x5678},
        "path": {"hash_size": 1, "hops": ["cc", "dd"]},
        "payload": {"dst": "a1", "src": "b2", "mac": "ef01", "ciphertext_len": 32}
    }
})

# ANON_REQ: route_type=3 but no actual TC (older firmware, TC fallback)
ephem = bytes(range(0x20, 0x40))  # 32-byte ephemeral pubkey
write_case("anon_req_tc_fallback", {
    "description": "ANON_REQ tdirect header but NO transport codes (older firmware)",
    "tags": ["anon_req", "tdirect", "tc_fallback"],
    "packet_hex": (
        bytes([mc_header(0x07, 3)])
        + bytes([path_len_byte(3, 1)]) + b"\x13\x35\x42"
        + bytes([0xd9]) + ephem + b"\xb2\xe2" + bytes(48)
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "tdirect",
        "payload_type": "ANON_REQ",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": ["13", "35", "42"]},
        "payload": {
            "dst": "d9",
            "ephem_prefix": ephem[:4].hex(),
            "mac": "b2e2",
            "ciphertext_len": 48
        }
    }
})

# GRP_TXT: basic group text
write_case("grp_txt_basic", {
    "description": "GRP_TXT flood, group text message",
    "tags": ["grp_txt", "flood", "group", "encrypted"],
    "packet_hex": group_packet(0x05, 0xCC, b"\xab\xcd", bytes(32)).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "GRP_TXT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {"channel_hash": "cc", "mac": "abcd", "ciphertext_len": 32}
    }
})

# TRACE: basic trace packet
write_case("trace_basic", {
    "description": "TRACE flood with tag, auth, and 2 trace hops",
    "tags": ["trace", "flood"],
    "packet_hex": trace_packet(
        0x12345678, 0xAABBCCDD, 0x00, b"\x11\x22"
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "TRACE",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {"trace_tag": 0x12345678, "trace_hops": 2}
    }
})

# TRACE: flags=2 means hash_size=4 (power of 2 encoding: 1 << 2 = 4)
write_case("trace_4byte_hash", {
    "description": "TRACE flood with 4-byte trace hashes (flags=0x02, hash_size=4)",
    "tags": ["trace", "flood", "4byte_hash"],
    "packet_hex": trace_packet(
        0xAABBCCDD, 0x11223344, 0x02, b"\xde\xad\xbe\xef\xca\xfe\xba\xbe"
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "TRACE",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {"trace_tag": 0xAABBCCDD, "trace_hops": 2}
    }
})

# MULTIPART: ACK inner type
write_case("multipart_ack", {
    "description": "MULTIPART flood, remaining=3, inner type=ACK",
    "tags": ["multipart", "flood", "ack"],
    "packet_hex": multipart_packet(
        3, 0x03, struct.pack("<I", 0xCAFEBABE)
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "MULTIPART",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {"multipart_remaining": 3, "multipart_inner": "ACK"}
    }
})

# CONTROL: DISCOVER_REQ
write_case("control_discover_req", {
    "description": "CONTROL flood, DISCOVER_REQ sub-type",
    "tags": ["control", "flood", "discover"],
    "packet_hex": control_packet(
        0x80, bytes([0x03]) + struct.pack("<I", 0xABCD1234)
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "CONTROL",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []},
        "payload": {"control_subtype": "DISCOVER_REQ"}
    }
})

# PATH: 3-byte hash, 1 hop
write_case("path_3byte_hash", {
    "description": "PATH flood, 1 hop with 3-byte hash",
    "tags": ["path", "flood", "3byte_hash", "encrypted"],
    "packet_hex": peer_packet(
        0x08, 1, 0xe6, 0xe9, b"\x2e\x47", bytes(46),
        path_hops=[b"\x1a\xff\xf3"], hash_size=3
    ).hex(),
    "valid": True,
    "expected": {
        "route_type": "flood",
        "payload_type": "PATH",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 3, "hops": ["1afff3"]},
        "payload": {"dst": "e6", "src": "e9", "mac": "2e47", "ciphertext_len": 46}
    }
})

# PATH: 4-byte hash (hash_size_code 3 = RESERVED, must be rejected)
write_case("path_4byte_hash", {
    "description": "PATH flood, 4-byte hash (reserved hash_size_code 3, invalid)",
    "tags": ["invalid", "path", "flood", "4byte_hash", "reserved_hash_size"],
    "packet_hex": peer_packet(
        0x08, 1, 0xe6, 0xe9, b"\x2e\x47", bytes(16),
        path_hops=[b"\xaa\xbb\xcc\xdd"], hash_size=4
    ).hex(),
    "valid": False,
    "expected": {
        "route_type": "flood",
        "payload_type": "PATH",
        "error": "bad_framing"
    }
})

# ── Invalid packets ───────────────────────────────────────────────

# Too short: 1 byte
write_case("too_short_1byte", {
    "description": "Packet too short (1 byte)",
    "tags": ["invalid", "too_short"],
    "packet_hex": "11",
    "valid": False,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "error": "too_short"
    }
})

# Too short: 2 bytes (need at least 3: header + path_len + 1 byte payload)
write_case("too_short_2bytes", {
    "description": "Packet too short (2 bytes, need >= 3)",
    "tags": ["invalid", "too_short"],
    "packet_hex": "1100",
    "valid": False,
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "error": "too_short"
    }
})

# Bad path_len: reserved hash_size_code 3 (bits 6-7 = 0b11)
bad_pkt = bytes([mc_header(0x02, 1), 0xC1]) + bytes(24)
write_case("bad_path_len_reserved_hash_size", {
    "description": "TXT_MSG flood, path_len has reserved hash_size_code 3",
    "tags": ["invalid", "bad_framing", "path", "reserved_hash_size"],
    "packet_hex": bad_pkt.hex(),
    "valid": False,
    "expected": {
        "route_type": "flood",
        "payload_type": "TXT_MSG",
        "error": "bad_framing"
    }
})

# Bad path_len: claims 33 hops (2B hash) but only 24 bytes remain
bad_pkt2 = bytes([mc_header(0x02, 1), 0x61]) + bytes(24)
write_case("bad_path_len", {
    "description": "TXT_MSG flood, path_len claims 33 hops (2B hash) but data is too short",
    "tags": ["invalid", "bad_framing", "path"],
    "packet_hex": bad_pkt2.hex(),
    "valid": False,
    "expected": {
        "route_type": "flood",
        "payload_type": "TXT_MSG",
        "error": "bad_framing"
    }
})

# Noise: random bytes that don't parse as meshcore
write_case("noise_packet", {
    "description": "Random bytes, not a valid MeshCore packet",
    "tags": ["invalid", "noise"],
    "packet_hex": "03d135839fc28d00",
    "valid": False,
    "expected": {
        "route_type": "tdirect",
        "payload_type": "REQ",
        "error": "not_meshcore"
    }
})

# Empty packet
write_case("empty_packet", {
    "description": "Empty packet (0 bytes)",
    "tags": ["invalid", "too_short"],
    "packet_hex": "",
    "valid": False,
    "expected": {
        "route_type": "flood",
        "payload_type": "REQ",
        "error": "too_short"
    }
})

# Bad advert: too short for pubkey+timestamp+signature
short_advert = advert_packet(b"")  # 102 bytes: hdr + path_len + 100 payload
truncated = short_advert[:50]  # cut in half
write_case("advert_truncated", {
    "description": "ADVERT flood, truncated mid-signature (50 bytes)",
    "tags": ["invalid", "advert", "truncated"],
    "packet_hex": truncated.hex(),
    "valid": True,  # parses as ADVERT but payload is bad
    "expected": {
        "route_type": "flood",
        "payload_type": "ADVERT",
        "payload_ver": 0,
        "transport_codes": None,
        "path": {"hash_size": 1, "hops": []}
    }
})

print(f"\nDone! {len(list(OUT.glob('*.json')))} test vectors written to {OUT}/")
