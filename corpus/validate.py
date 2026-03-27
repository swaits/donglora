#!/usr/bin/env python3
"""Validate MeshCore test corpus against schema and decoder."""
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema", "cobs", "pyserial", "pycryptodome"]
# ///

import json
import re
import sys
from pathlib import Path

import jsonschema

# Add tools/ to path so we can import the decoder
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from meshcore_rx import decode_meshcore_packet  # noqa: E402

CORPUS_DIR = Path(__file__).parent
SCHEMA_PATH = CORPUS_DIR / "schema.json"

# ANSI escape stripper
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def find_test_cases() -> list[Path]:
    cases = []
    for d in ["hand", "generated"]:
        p = CORPUS_DIR / d
        if p.is_dir():
            cases.extend(sorted(p.glob("*.json")))
    return cases


def validate_schema(case: dict, schema: dict, path: Path) -> list[str]:
    """Validate a test case against the JSON schema. Returns list of errors."""
    errors = []
    try:
        jsonschema.validate(case, schema)
    except jsonschema.ValidationError as e:
        errors.append(f"Schema: {e.message}")
    return errors


def validate_decode(case: dict, path: Path) -> list[str]:
    """Run the decoder and check output against expected fields."""
    errors = []
    packet = bytes.fromhex(case["packet_hex"]) if case["packet_hex"] else b""
    expected = case["expected"]

    # Run decoder — must not crash
    try:
        raw_output = decode_meshcore_packet(packet)
    except Exception as e:
        errors.append(f"Decoder crashed: {e}")
        return errors

    output = strip_ansi(raw_output)

    if case["valid"]:
        # Valid packet: should contain the expected payload type name
        ptype = expected["payload_type"]
        if ptype not in output:
            errors.append(f"Expected '{ptype}' in output, got: {output[:120]}")

        # Check route type
        rtype = expected["route_type"]
        if rtype not in output:
            errors.append(f"Expected route '{rtype}' in output, got: {output[:120]}")

        # Check path hops if specified
        if "path" in expected:
            exp_path = expected["path"]
            for hop in exp_path["hops"]:
                if hop not in output:
                    errors.append(f"Expected hop '{hop}' in output")

        # Check payload-specific fields
        payload = expected.get("payload")
        if payload:
            _check_payload(payload, output, errors)

        # Should NOT contain error markers
        for marker in ["<too short>", "<not meshcore>", "<bad framing>"]:
            if marker in output:
                errors.append(f"Valid packet produced error marker: {marker}")

    else:
        # Invalid packet: must not crash. Error marker check is best-effort
        # (random mutations may accidentally produce parseable packets).
        pass  # decoder didn't crash — that's the key requirement

    return errors


def _check_payload(payload: dict, output: str, errors: list[str]):
    """Check payload-specific fields in the decoder output."""
    if "ack_crc" in payload:
        crc_hex = f"0x{payload['ack_crc']:08x}"
        if crc_hex not in output:
            errors.append(f"Expected CRC '{crc_hex}' in output")

    if "dst" in payload:
        if payload["dst"] not in output:
            errors.append(f"Expected dst='{payload['dst']}' in output")

    if "src" in payload:
        if payload["src"] not in output:
            errors.append(f"Expected src='{payload['src']}' in output")

    if "mac" in payload:
        if payload["mac"] not in output:
            errors.append(f"Expected mac='{payload['mac']}' in output")

    if "channel_hash" in payload:
        if payload["channel_hash"] not in output:
            errors.append(f"Expected ch='{payload['channel_hash']}' in output")

    if "ciphertext_len" in payload:
        ct_str = f"[{payload['ciphertext_len']}B]"
        if ct_str not in output:
            errors.append(f"Expected '{ct_str}' in output")

    if "pubkey_prefix" in payload:
        pk = payload["pubkey_prefix"]
        if pk not in output:
            errors.append(f"Expected pubkey prefix '{pk}' in output")

    if "advert" in payload and payload["advert"] is not None:
        advert = payload["advert"]
        if "name" in advert and advert["name"] is not None:
            if advert["name"] not in output:
                errors.append(f"Expected name '{advert['name']}' in output")
        if "node_type" in advert:
            if advert["node_type"] not in output:
                errors.append(f"Expected node_type '{advert['node_type']}' in output")
        if "location" in advert and advert["location"] is not None:
            loc = advert["location"]
            lat_str = f"{loc['lat']:.4f}"
            if lat_str not in output:
                errors.append(f"Expected lat '{lat_str}' in output")

    if "ephem_prefix" in payload:
        ep = payload["ephem_prefix"]
        if ep not in output:
            errors.append(f"Expected ephemeral prefix '{ep}' in output")

    if "multipart_remaining" in payload:
        r = payload["multipart_remaining"]
        if f"remaining={r}" not in output.replace(" ", ""):
            errors.append(f"Expected remaining={r} in output")

    if "multipart_inner" in payload:
        inner = payload["multipart_inner"]
        if inner not in output:
            errors.append(f"Expected inner type '{inner}' in output")

    if "control_subtype" in payload:
        sub = payload["control_subtype"]
        if sub not in output:
            errors.append(f"Expected control subtype '{sub}' in output")


def main():
    schema = load_schema()
    cases = find_test_cases()

    if not cases:
        print("No test cases found!")
        sys.exit(1)

    passed = 0
    failed = 0
    total_errors: list[tuple[str, list[str]]] = []

    for path in cases:
        case = json.loads(path.read_text())
        name = f"{path.parent.name}/{path.stem}"

        errors = validate_schema(case, schema, path)
        errors.extend(validate_decode(case, path))

        if errors:
            failed += 1
            total_errors.append((name, errors))
            print(f"  \033[1;31mFAIL\033[0m {name}")
            for e in errors:
                print(f"       {e}")
        else:
            passed += 1
            print(f"  \033[32mPASS\033[0m {name}")

    print()
    print(f"\033[1m{passed + failed} tests: {passed} passed, {failed} failed\033[0m")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
