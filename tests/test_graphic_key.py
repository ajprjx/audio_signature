"""Tests for core.graphic_key (payload encoding, image composition, QR decode)."""

from __future__ import annotations

import base64
import json
import zlib

from PIL import Image

from core.graphic_key import (
    CANVAS_H,
    CANVAS_W,
    _ZLIB_PREFIX,
    _build_payload,
    _encode_payload,
    build_graphic_key,
    load_graphic_key_payload,
)


def test_build_payload_structure():
    md = {"title": "T", "artist": "A", "timestamp": "2024-01-01T00:00:00Z"}
    fp = {"fingerprint": "FP", "fingerprint_hash": "abc123", "duration": 12.5}
    p = _build_payload(md, fp)
    assert p["v"] == 1
    assert p["title"] == "T"
    assert p["artist"] == "A"
    assert p["duration"] == 12.5
    assert p["fp_hash"] == "abc123"
    assert p["fingerprint"] == "FP"
    assert p["ts"] == "2024-01-01T00:00:00Z"


def test_build_payload_supplies_defaults():
    p = _build_payload({}, {})
    assert p["title"] == "Unknown Title"
    assert p["artist"] == "Unknown Artist"
    assert p["fp_hash"] == ""
    assert p["fingerprint"] == ""
    # Timestamp should be auto-generated and ISO-8601 looking.
    assert p["ts"].endswith("Z") and "T" in p["ts"]


def test_encode_payload_roundtrip():
    p = {"v": 1, "title": "X", "fingerprint": "AQAA" * 16}
    encoded = _encode_payload(p)
    assert encoded.startswith(_ZLIB_PREFIX)
    raw = zlib.decompress(base64.b64decode(encoded[len(_ZLIB_PREFIX):]))
    assert json.loads(raw.decode("utf-8")) == p


def test_build_graphic_key_dimensions(sample_mp3, fingerprint_data, tmp_path):
    out = str(tmp_path / "key.png")
    build_graphic_key(
        sample_mp3,
        out,
        {"title": "T", "artist": "A", "timestamp": "2024-01-15T10:30:00Z"},
        fingerprint_data,
    )
    img = Image.open(out)
    assert img.size == (CANVAS_W, CANVAS_H)
    assert img.mode == "RGB"


def test_graphic_key_qr_roundtrip(graphic_key_png, fingerprint_data, require_qr_backend):
    payload = load_graphic_key_payload(graphic_key_png)
    assert payload["v"] == 1
    assert payload["fp_hash"] == fingerprint_data["fingerprint_hash"]
    assert payload["title"] == "Test Sweep"
    assert payload["artist"] == "pytest"


def test_graphic_key_compact_fallback_when_oversized(
    sample_mp3, tmp_path, require_qr_backend
):
    # Force the compact fallback path by giving an incompressible fingerprint
    # that exceeds version-40 QR capacity even at error-correction L.
    import secrets

    huge_fp = secrets.token_urlsafe(6000)
    fingerprint_data = {
        "fingerprint": huge_fp,
        "fingerprint_hash": "deadbeefcafebabe",
        "duration": 10.0,
        "fingerprint_bytes": b"\x00" * 120,
    }
    out = str(tmp_path / "huge_key.png")
    build_graphic_key(
        sample_mp3,
        out,
        {"title": "Huge", "artist": "Pytest", "timestamp": "2024-01-15T10:30:00Z"},
        fingerprint_data,
    )

    payload = load_graphic_key_payload(out)
    assert payload.get("fp_truncated") is True
    assert payload["fingerprint"] == ""
    assert payload["fp_hash"] == "deadbeefcafebabe"


def test_load_legacy_base64_payload(tmp_path, require_qr_backend):
    """Pre-Z1 keys encoded as plain base64 JSON must still decode."""
    import qrcode

    payload = {
        "v": 1,
        "title": "Legacy",
        "artist": "Old",
        "duration": 30.0,
        "fp_hash": "abc",
        "fingerprint": "AQAA",
        "ts": "2020-01-01T00:00:00Z",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    # NOTE: no Z1: prefix — exercises the legacy decode path.
    data_str = base64.b64encode(raw).decode("ascii")
    qr = qrcode.QRCode(version=None, box_size=10, border=2)
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="white", back_color="#0A0A0A").convert("RGB")
    out = str(tmp_path / "legacy.png")
    img.save(out)

    decoded = load_graphic_key_payload(out)
    assert decoded == payload
