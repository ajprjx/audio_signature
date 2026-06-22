"""Feature 2: glyph layer — ultra-smooth (low band) decodable color field."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from core import glyph


def _payload(n, seed=0):
    return np.random.default_rng(seed).integers(0, 256, n, dtype=np.uint8).tobytes()


def test_round_trips_a_payload():
    payload = _payload(120)
    assert glyph.decode_glyph(glyph.encode_glyph(payload)) == payload


def test_capacity_fits_the_lean_chain():
    # MuSig2 (96B) + fp digest + meta must fit; target >= 150 B.
    assert glyph.CAPACITY_BYTES >= 150


def test_output_is_256x256_rgb():
    img = glyph.encode_glyph(_payload(80))
    assert img.size == (256, 256) and img.mode == "RGB"


def test_survives_png_round_trip():
    payload = _payload(120, seed=2)
    buf = io.BytesIO()
    glyph.encode_glyph(payload).save(buf, format="PNG")
    buf.seek(0)
    assert glyph.decode_glyph(Image.open(buf)) == payload


def test_round_trips_many_payloads_at_ber_zero():
    for seed in range(20):
        payload = _payload(glyph.CAPACITY_BYTES, seed=seed)
        assert glyph.decode_glyph(glyph.encode_glyph(payload)) == payload


def test_is_ultra_smooth():
    arr = np.asarray(glyph.encode_glyph(_payload(glyph.CAPACITY_BYTES)), float)
    grad = np.abs(np.diff(arr, axis=0)).mean() + np.abs(np.diff(arr, axis=1)).mean()
    assert grad < 1.2  # smoother than the default (R=18) codec


def test_rejects_oversized_payload():
    with pytest.raises(ValueError):
        glyph.encode_glyph(_payload(glyph.CAPACITY_BYTES + 1))


def test_cohesion_recenters_on_base_hue():
    # The cohesion transform should pull the field off neutral gray toward the
    # cool base hue: blue channel clearly dominant, red clearly recessive.
    mean = np.asarray(glyph.encode_glyph(_payload(150)), float).reshape(-1, 3).mean(0)
    r, g, b = mean
    assert b > g > r
    assert b - r > 30
    assert not (118 < r < 138 and 118 < g < 138 and 118 < b < 138)  # not gray
