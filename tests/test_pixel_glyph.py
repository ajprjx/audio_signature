"""Pixel glyph encode/decode roundtrip + edge-case tests."""

from __future__ import annotations

import os
import random
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from core.pixel_glyph import (
    GLYPH_SIZE,
    LUT_NAMES,
    _LUT_ID,
    _MANIFEST_COORDS,
    _SPIRAL_COORDS,
    _domain_warp,
    _extract_triplicated,
    _julia_field,
    _parse_manifest,
    apply_lut,
    decode_glyph,
    generate_glyph,
    get_lut_curve,
    invert_lut,
    list_luts,
    render_glyph_display,
    render_glyph_image,
    verify_glyph_against_mp3,
)


def test_list_luts_has_expected_set():
    assert set(list_luts()) == set(LUT_NAMES)


def test_lut_inverse_identity_byte_level():
    """For every LUT, invert(apply(raw)) must recover raw for all 256 byte values."""
    for lut_name in list_luts():
        lut_id = _LUT_ID[lut_name]
        for v in range(256):
            r_t, g_t, b_t = apply_lut(v, v, v, lut_name)
            r_back, g_back, b_back = invert_lut(r_t, g_t, b_t, lut_id)
            assert (r_back, g_back, b_back) == (v, v, v), f"{lut_name} not bijective at {v}"


def test_lut_monotonicity():
    for lut_name in list_luts():
        for ch in ("R", "G", "B"):
            curve = get_lut_curve(lut_name, ch)
            assert np.all(np.diff(curve.astype(int)) > 0), f"{lut_name}.{ch} not monotonic"


def test_spiral_and_manifest_partition():
    spiral = set(_SPIRAL_COORDS)
    manifest = set(_MANIFEST_COORDS)
    assert len(spiral) == 4080
    assert len(manifest) == 16
    assert spiral.isdisjoint(manifest)
    assert spiral | manifest == {(r, c) for r in range(GLYPH_SIZE) for c in range(GLYPH_SIZE)}


def test_extract_triplicated_unit():
    # Build a fake stream where every triplicated triplet's first byte is the index.
    stream = bytearray()
    for i in range(10):
        stream += bytes((i, i, i))
    out = _extract_triplicated(stream, 0, 10)
    assert out == bytes(range(10))


def test_roundtrip(tmp_path, sample_mp3, require_fpcalc):
    out = generate_glyph(sample_mp3, str(tmp_path / "glyph.png"), lut_name="magma")
    decoded = decode_glyph(str(tmp_path / "glyph.png"))
    assert decoded["verified"] is True
    assert decoded["crc_match"] is True
    assert decoded["lut_name"] == "magma"
    assert decoded["fingerprint_hex"] == out["fingerprint_hex"]
    # Display PNG should be present and 256x256.
    assert "display_path" in out
    assert os.path.exists(out["display_path"])
    display = Image.open(out["display_path"])
    assert display.size == (256, 256)


def test_all_luts(tmp_path, sample_mp3, require_fpcalc):
    for lut in list_luts():
        out = generate_glyph(
            sample_mp3, str(tmp_path / f"glyph_{lut}.png"), lut_name=lut
        )
        decoded = decode_glyph(str(tmp_path / f"glyph_{lut}.png"))
        assert decoded["verified"] is True
        assert decoded["fingerprint_hex"] == out["fingerprint_hex"]
        assert decoded["lut_name"] == lut


def test_rejects_jpeg_output(tmp_path, sample_mp3, require_fpcalc):
    with pytest.raises(ValueError, match="PNG"):
        generate_glyph(sample_mp3, str(tmp_path / "glyph.jpg"))


def test_decode_rejects_wrong_size(tmp_path):
    # Save a 32×32 PNG and try to decode it.
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    out = str(tmp_path / "tiny.png")
    img.save(out, "PNG")
    with pytest.raises(ValueError, match="64"):
        decode_glyph(out)


def test_decode_rejects_jpeg_input(tmp_path):
    img = Image.new("RGB", (GLYPH_SIZE, GLYPH_SIZE), (0, 0, 0))
    out = str(tmp_path / "glyph.jpg")
    img.save(out, "JPEG")
    with pytest.raises(ValueError, match="PNG"):
        decode_glyph(out)


def test_render_glyph_image_dims(sample_mp3, require_fpcalc):
    img = render_glyph_image(sample_mp3, lut_name="viridis")
    assert img.size == (GLYPH_SIZE, GLYPH_SIZE)
    assert img.mode == "RGB"


def test_render_glyph_image_unknown_lut_raises(sample_mp3, require_fpcalc):
    with pytest.raises(ValueError, match="Unknown LUT"):
        render_glyph_image(sample_mp3, lut_name="not_a_real_lut")


def test_manifest_fields_present(sample_mp3, glyph_png):
    img = Image.open(glyph_png).convert("RGB")
    pixels = img.load()
    manifest = bytearray()
    for row, col in _MANIFEST_COORDS:
        r, g, b = pixels[col, row]
        manifest.extend((r, g, b))
    info = _parse_manifest(bytes(manifest))
    assert info["version"] == 0x01
    assert info["lut_id"] == _LUT_ID["magma"]
    assert info["ecc_level"] == 1  # RS(255,120)
    assert info["fingerprint_len"] == 120
    assert info["duration"] > 0
    # CRC32 of the decoded glyph payload must match what we stored.
    decoded = decode_glyph(glyph_png)
    assert zlib.crc32(decoded["fingerprint_bytes"]) & 0xFFFFFFFF == info["stored_crc"]


def test_rs_recovers_from_pixel_errors(sample_mp3, glyph_png):
    """Corrupt a handful of fingerprint pixels and confirm RS still recovers."""
    img = Image.open(glyph_png).convert("RGB")
    pixels = img.load()

    rng = random.Random(7)
    # Flip the first channel of 5 fingerprint pixels — well within the RS(255,120)
    # correction budget (up to 60 errors).
    for i in rng.sample(range(120), 5):
        row, col = _SPIRAL_COORDS[i]
        r, g, b = pixels[col, row]
        pixels[col, row] = ((r + 64) % 256, g, b)

    corrupted = str(glyph_png).replace(".png", "_corrupt.png")
    img.save(corrupted, "PNG")

    clean = decode_glyph(glyph_png)
    recovered = decode_glyph(corrupted)
    assert recovered["fingerprint_hex"] == clean["fingerprint_hex"]
    assert recovered["crc_match"] is True


def test_verify_glyph_against_same_mp3(sample_mp3, glyph_png):
    result = verify_glyph_against_mp3(glyph_png, sample_mp3)
    assert result["match"] is True
    assert result["bytes_match"] is True
    assert result["crc_match"] is True


def test_verify_glyph_against_different_mp3(glyph_png, sample_mp3_alt, require_fpcalc):
    result = verify_glyph_against_mp3(glyph_png, sample_mp3_alt)
    assert result["match"] is False
    assert result["bytes_match"] is False


def test_bpm_extracted_into_manifest(tmp_path, sample_mp3, require_fpcalc):
    from mutagen.id3 import ID3, ID3NoHeaderError, TBPM

    try:
        tags = ID3(sample_mp3)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TBPM(encoding=3, text=["128"]))
    tags.save(sample_mp3)

    out = str(tmp_path / "glyph_bpm.png")
    generate_glyph(sample_mp3, out, lut_name="magma", also_save_display=False)
    decoded = decode_glyph(out)
    assert decoded["bpm"] == 128


def test_decode_duration_close_to_source(sample_mp3, glyph_png):
    decoded = decode_glyph(glyph_png)
    # float32 manifest field; sample is ~10s.
    assert abs(decoded["duration"] - 10.0) < 0.5


# --- Julia + domain-warp visual layer ---------------------------------------


def test_julia_field_shape_and_range():
    field = _julia_field(b"\x12\x34\x56\x78" + b"\x00" * 116, size=64)
    assert field.shape == (64, 64)
    assert field.dtype == np.float32
    assert field.min() >= 0.0
    assert field.max() <= 1.0


def test_julia_field_deterministic():
    seed = b"\xa1\xb2\xc3\xd4" + b"\x00" * 116
    a = _julia_field(seed, size=64)
    b = _julia_field(seed, size=64)
    assert np.array_equal(a, b)


def test_julia_field_differs_for_different_seeds():
    a = _julia_field(b"\x10\x20\x30\x40" + b"\x00" * 116, size=64)
    b = _julia_field(b"\xc0\xd0\xe0\xf0" + b"\x00" * 116, size=64)
    assert not np.array_equal(a, b)


def test_domain_warp_preserves_range():
    field = np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64)
    waveform = [0.5] * 128
    warped = _domain_warp(field, waveform)
    assert warped.shape == field.shape
    assert warped.min() >= 0.0
    assert warped.max() <= 1.0


def test_julia_warp_roundtrip(tmp_path, sample_mp3, require_fpcalc):
    """Decode must still succeed after the visual layer is applied."""
    out = generate_glyph(
        sample_mp3, str(tmp_path / "g.png"), lut_name="magma", also_save_display=False
    )
    decoded = decode_glyph(str(tmp_path / "g.png"))
    assert decoded["verified"] is True
    assert decoded["fingerprint_hex"] == out["fingerprint_hex"]


def test_render_glyph_display_size(sample_mp3, require_fpcalc):
    img = render_glyph_display(sample_mp3, lut_name="plasma")
    assert img.size == (256, 256)
    assert img.mode == "RGB"


def test_display_glyph_not_decodable(tmp_path, sample_mp3, require_fpcalc):
    """256px display glyphs must not survive a decode_glyph call."""
    img = render_glyph_display(sample_mp3, lut_name="plasma")
    p = tmp_path / "display.png"
    img.save(str(p), format="PNG")
    with pytest.raises(ValueError, match="64"):
        decode_glyph(str(p))


def test_visual_layer_preserves_r_channel(sample_mp3, glyph_png):
    """Spot-check: decoded fingerprint matches CRC even with G/B modulated."""
    decoded = decode_glyph(glyph_png)
    assert decoded["crc_match"] is True
    assert decoded["verified"] is True
