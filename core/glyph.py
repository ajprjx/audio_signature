"""Glyph layer: the canonical ultra-smooth 256x256 signed-glyph field.

Wraps :class:`core.spectral.SpectralCodec` at a low frequency band so the
rendered field is an ultra-smooth, atmospheric color bloom (Path B) while every
pixel stays load-bearing and the payload round-trips losslessly (BER 0).

A universal **cohesion transform** is applied before the single 8-bit rounding:
an invertible 3x3 colour map that correlates the channels (shared luminance +
gentle per-channel chroma) and recenters them on a cool base hue, so the field
reads as a moody atmospheric bloom rather than a rainbow. Decode inverts the
transform first, then runs the codec. The map is well-conditioned (eigenvalues
{GC, GI, GI}), so it does not break BER 0 and the field stays within [0, 255].
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from core.spectral import SpectralCodec

FREQ_R = 10  # ultra-smooth band

# Cohesion transform: D = BASE + (field - 128) @ M.T
GC = 0.9                       # shared-luminance gain
GI = 0.62                      # per-channel chroma gain
BASE = np.array([70.0, 95.0, 125.0])  # cool base hue (teal/indigo slate)
_M = GI * np.eye(3) + ((GC - GI) / 3.0) * np.ones((3, 3))
_MINV = np.linalg.inv(_M)

_CODEC = SpectralCodec(freq_r=FREQ_R)
CAPACITY_BYTES = _CODEC.capacity_bytes


def encode_glyph(payload: bytes) -> Image.Image:
    """Encode bytes into the ultra-smooth, cohesively-coloured glyph field."""
    field = _CODEC.encode_to_field(payload)          # channel mean ~128
    disp = BASE + (field - 128.0) @ _M.T
    rgb = np.clip(np.round(disp), 0, 255).astype("uint8")
    return Image.fromarray(rgb, "RGB")


def decode_glyph(img: Image.Image) -> bytes:
    """Recover the bytes encoded by :func:`encode_glyph`."""
    arr = np.asarray(img.convert("RGB"), dtype=float)
    field = (arr - BASE) @ _MINV.T + 128.0
    return _CODEC.decode_from_field(field)
