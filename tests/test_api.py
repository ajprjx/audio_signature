"""End-to-end Flask API tests using the test client."""

from __future__ import annotations

import base64
import io

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config.update({"TESTING": True})
    with app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<html" in resp.data.lower() or b"<!doctype" in resp.data.lower()


def test_encode_requires_file(client):
    resp = client.post("/api/encode", data={})
    assert resp.status_code == 400


def test_encode_rejects_bad_extension(client):
    data = {"file": (io.BytesIO(b"junk"), "song.wav")}
    resp = client.post("/api/encode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "mp3" in resp.get_json()["error"].lower()


def test_encode_rejects_bad_lut(client, sample_mp3, require_fpcalc):
    with open(sample_mp3, "rb") as fh:
        data = {
            "file": (io.BytesIO(fh.read()), "sample.mp3"),
            "lut": "not_real",
        }
        resp = client.post("/api/encode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "LUT" in resp.get_json()["error"]


def test_encode_happy_path(client, sample_mp3, require_fpcalc):
    with open(sample_mp3, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "sample.mp3")}
        resp = client.post("/api/encode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    j = resp.get_json()
    for key in ("graphic_key", "glyph", "glyph_display", "metadata"):
        assert key in j
    # PNG signature.
    assert base64.b64decode(j["graphic_key"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert base64.b64decode(j["glyph"])[:8] == b"\x89PNG\r\n\x1a\n"
    md = j["metadata"]
    assert md["lut_name"] == "magma"
    assert len(md["fingerprint_hash"]) == 16
    assert md["duration"] > 0


def test_decode_endpoint(client, graphic_key_png, require_qr_backend):
    with open(graphic_key_png, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "key.png")}
        resp = client.post("/api/decode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    j = resp.get_json()
    assert j["verified"] is True
    assert j["title"] == "Test Sweep"
    assert j["fingerprint_hash"]


def test_decode_glyph_endpoint(client, glyph_png):
    with open(glyph_png, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "glyph.png")}
        resp = client.post(
            "/api/decode/glyph", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    j = resp.get_json()
    assert j["verified"] is True
    assert "fingerprint_hex" in j
    # Raw bytes should not be returned over the wire.
    assert "fingerprint_bytes" not in j


def test_decode_rejects_bad_extension(client):
    data = {"file": (io.BytesIO(b"junk"), "key.gif")}
    resp = client.post("/api/decode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_verify_happy_path(client, sample_mp3, graphic_key_png, require_qr_backend, require_fpcalc):
    with open(sample_mp3, "rb") as mp3_fh, open(graphic_key_png, "rb") as png_fh:
        data = {
            "mp3": (io.BytesIO(mp3_fh.read()), "sample.mp3"),
            "graphic_key": (io.BytesIO(png_fh.read()), "key.png"),
        }
        resp = client.post("/api/verify", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    j = resp.get_json()
    assert j["match"] is True
    assert j["similarity"] >= 0.85
    assert "key_metadata" in j and "mp3_metadata" in j


def test_verify_rejects_missing_fields(client):
    resp = client.post("/api/verify", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_encode_size_64_default_decodable(client, sample_mp3, require_fpcalc):
    with open(sample_mp3, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "sample.mp3"), "size": "64"}
        resp = client.post("/api/encode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    j = resp.get_json()
    assert j["glyph_size"] == 64
    assert j["glyph_decodable"] is True
    # 64px glyph PNG embedded in base64 should decode to a 64×64 image.
    from PIL import Image as _Image

    img = _Image.open(io.BytesIO(base64.b64decode(j["glyph"])))
    assert img.size == (64, 64)


def test_encode_size_256_display_only(client, sample_mp3, require_fpcalc):
    with open(sample_mp3, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "sample.mp3"), "size": "256"}
        resp = client.post("/api/encode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    j = resp.get_json()
    assert j["glyph_size"] == 256
    assert j["glyph_decodable"] is False
    from PIL import Image as _Image

    img = _Image.open(io.BytesIO(base64.b64decode(j["glyph"])))
    assert img.size == (256, 256)
    # The upscaled-display field is always present too.
    display = _Image.open(io.BytesIO(base64.b64decode(j["glyph_display"])))
    assert display.size == (256, 256)


def test_encode_rejects_bad_size(client, sample_mp3, require_fpcalc):
    with open(sample_mp3, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "sample.mp3"), "size": "128"}
        resp = client.post("/api/encode", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "size" in resp.get_json()["error"].lower()


def test_decode_glyph_size_256_rejected(client, glyph_png):
    with open(glyph_png, "rb") as fh:
        data = {"file": (io.BytesIO(fh.read()), "glyph.png"), "size": "256"}
        resp = client.post(
            "/api/decode/glyph", data=data, content_type="multipart/form-data"
        )
    assert resp.status_code == 400
    assert "display-only" in resp.get_json()["error"]
