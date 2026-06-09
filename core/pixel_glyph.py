"""64×64 pixel glyph encoder/decoder for audio fingerprints.

Encodes a fixed 120-byte fingerprint, Reed–Solomon parity, and a 128-frame RMS
waveform into a self-contained PNG. No QR code or sidecar files required.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from typing import Any

import math

import numpy as np
from PIL import Image
from reedsolo import RSCodec
from scipy.ndimage import map_coordinates

from .fingerprint import (
    FINGERPRINT_BYTE_LEN,
    generate_fingerprint,
)
from .metadata import read_metadata
from .waveform import get_rms_envelope

# --- Layout constants -------------------------------------------------------

GLYPH_SIZE = 64
SPIRAL_PIXELS = 4080
MANIFEST_PIXELS = 16
MANIFEST_ROWS = range(60, 64)
MANIFEST_COLS = range(60, 64)

FP_SEGMENT_PIXELS = 120
ECC_SEGMENT_PIXELS = 120
WAVE_SEGMENT_PIXELS = 128
HEADER_PIXELS = FP_SEGMENT_PIXELS + ECC_SEGMENT_PIXELS + WAVE_SEGMENT_PIXELS

STREAM_BYTES = SPIRAL_PIXELS * 3
PADDING_BYTES = STREAM_BYTES - HEADER_PIXELS * 3

MANIFEST_VERSION = 0x01
ECC_RS_255_120 = 1

LUT_NAMES = ("magma", "viridis", "inferno", "plasma", "copper")
_LUT_ID = {name: idx for idx, name in enumerate(LUT_NAMES)}

# --- Coordinate generation --------------------------------------------------


def _spiral_coords_outside_in(size: int) -> list[tuple[int, int]]:
    """Clockwise inward spiral over an ``size × size`` grid."""
    coords: list[tuple[int, int]] = []
    top, bottom, left, right = 0, size - 1, 0, size - 1
    while top <= bottom and left <= right:
        for col in range(left, right + 1):
            coords.append((top, col))
        top += 1
        for row in range(top, bottom + 1):
            coords.append((row, right))
        right -= 1
        if top <= bottom:
            for col in range(right, left - 1, -1):
                coords.append((bottom, col))
            bottom -= 1
        if left <= right:
            for row in range(bottom, top - 1, -1):
                coords.append((row, left))
            left += 1
    return coords


_MANIFEST_COORDS: list[tuple[int, int]] = [
    (row, col) for row in MANIFEST_ROWS for col in MANIFEST_COLS
]
_MANIFEST_SET = set(_MANIFEST_COORDS)
_SPIRAL_COORDS: list[tuple[int, int]] = [
    c for c in _spiral_coords_outside_in(GLYPH_SIZE) if c not in _MANIFEST_SET
]

assert len(_SPIRAL_COORDS) == SPIRAL_PIXELS
assert len(_MANIFEST_COORDS) == MANIFEST_PIXELS

# --- LUT generation ---------------------------------------------------------


def _finalize_monotonic(curve: np.ndarray) -> np.ndarray:
    """Spread a near-monotonic curve into a strict bijection on 0..255."""
    weights = curve.astype(np.float64) + 1.0
    targets = np.cumsum(weights)
    targets = targets / targets[-1] * 255.0
    out = np.zeros(256, dtype=np.uint8)
    out[0] = 0
    for i in range(1, 256):
        out[i] = max(int(round(targets[i])), int(out[i - 1]) + 1)
    if out[-1] > 255:
        return np.arange(256, dtype=np.uint8)
    out[-1] = 255
    return out


def _build_channel_curve(stops: list[tuple[float, float]]) -> np.ndarray:
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    ys = np.array([s[1] for s in stops], dtype=np.float64)
    for i in range(1, len(ys)):
        if ys[i] <= ys[i - 1]:
            ys[i] = min(255.0, ys[i - 1] + 1.0)
    samples = np.linspace(0, 255, 256)
    curve = np.clip(np.round(np.interp(samples, xs, ys)), 0, 255).astype(np.uint8)
    return _finalize_monotonic(curve)


def _lut_stops() -> dict[str, dict[str, list[tuple[float, float]]]]:
    """Hand-tuned anchor stops per LUT channel (input 0–255 → output 0–255)."""
    return {
        "magma": {
            "R": [(0, 0), (64, 20), (128, 120), (192, 220), (255, 252)],
            "G": [(0, 0), (64, 10), (128, 50), (192, 140), (255, 230)],
            "B": [(0, 4), (64, 60), (128, 110), (192, 80), (255, 180)],
        },
        "viridis": {
            "R": [(0, 40), (64, 50), (128, 30), (192, 180), (255, 252)],
            "G": [(0, 15), (64, 100), (128, 160), (192, 210), (255, 230)],
            "B": [(0, 80), (64, 120), (128, 100), (192, 60), (255, 140)],
        },
        "inferno": {
            "R": [(0, 0), (64, 80), (128, 200), (192, 250), (255, 252)],
            "G": [(0, 0), (64, 20), (128, 60), (192, 160), (255, 240)],
            "B": [(0, 4), (64, 40), (128, 20), (192, 40), (255, 180)],
        },
        "plasma": {
            "R": [(0, 10), (64, 80), (128, 180), (192, 240), (255, 252)],
            "G": [(0, 0), (64, 20), (128, 40), (192, 120), (255, 230)],
            "B": [(0, 60), (64, 120), (128, 140), (192, 100), (255, 80)],
        },
        "copper": {
            "R": [(0, 0), (64, 60), (128, 140), (192, 200), (255, 252)],
            "G": [(0, 0), (64, 40), (128, 90), (192, 140), (255, 200)],
            "B": [(0, 0), (64, 20), (128, 50), (192, 70), (255, 120)],
        },
    }


def _build_inverse(curve: np.ndarray) -> np.ndarray:
    inverse = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        inverse[int(curve[i])] = i
    return inverse


_LUT_FORWARD: dict[str, dict[str, np.ndarray]] = {}
_LUT_INVERSE: dict[int, dict[str, np.ndarray]] = {}

for _name in LUT_NAMES:
    _channels: dict[str, np.ndarray] = {}
    _inv_channels: dict[str, np.ndarray] = {}
    for _ch in ("R", "G", "B"):
        _curve = _build_channel_curve(_lut_stops()[_name][_ch])
        assert np.all(np.diff(_curve.astype(int)) > 0), f"{_name}.{_ch} not monotonic"
        _channels[_ch] = _curve
        _inv_channels[_ch] = _build_inverse(_curve)
    _LUT_FORWARD[_name] = _channels
    _LUT_INVERSE[_LUT_ID[_name]] = _inv_channels


def get_lut_curve(lut_name: str, channel: str) -> np.ndarray:
    """Return the forward LUT curve for ``channel`` (``R``, ``G``, or ``B``)."""
    return _LUT_FORWARD[lut_name][channel.upper()]


def apply_lut(raw_r: int, raw_g: int, raw_b: int, lut_name: str) -> tuple[int, int, int]:
    """Map raw byte values through the perceptual LUT curves."""
    lut = _LUT_FORWARD[lut_name]
    return (
        int(lut["R"][raw_r]),
        int(lut["G"][raw_g]),
        int(lut["B"][raw_b]),
    )


def invert_lut(tone_r: int, tone_g: int, tone_b: int, lut_id: int) -> tuple[int, int, int]:
    """Invert tone-mapped channel values back to raw bytes."""
    inv = _LUT_INVERSE[lut_id]
    return (
        int(inv["R"][tone_r]),
        int(inv["G"][tone_g]),
        int(inv["B"][tone_b]),
    )


# --- Stream assembly --------------------------------------------------------


def _triplicate(data: bytes) -> bytes:
    return bytes(b for byte in data for b in (byte, byte, byte))


def _extract_triplicated(stream: bytearray, pixel_offset: int, count: int) -> bytes:
    """Read ``count`` bytes from triplicated RGB pixels starting at ``pixel_offset``."""
    out = bytearray()
    for i in range(count):
        base = (pixel_offset + i) * 3
        out.append(stream[base])
    return bytes(out)


def _build_padding(seed: bytes) -> bytes:
    padding = bytearray()
    block = seed
    while len(padding) < PADDING_BYTES:
        block = hashlib.sha256(block).digest()
        padding.extend(block)
    return bytes(padding[:PADDING_BYTES])


def _rs_encode(fingerprint_bytes: bytes) -> tuple[bytes, bytes]:
    rsc = RSCodec(120)
    encoded = bytearray(rsc.encode(fingerprint_bytes))
    return bytes(encoded[:120]), bytes(encoded[120:240])


def _rs_decode(data_bytes: bytes, parity_bytes: bytes) -> tuple[bytes, int]:
    rsc = RSCodec(120)
    codeword = data_bytes + parity_bytes
    recovered, _, errata_pos = rsc.decode(codeword)
    corrections = len(errata_pos) if errata_pos else 0
    return bytes(recovered[:FINGERPRINT_BYTE_LEN]), corrections


def _build_manifest_bytes(
    lut_id: int,
    fingerprint_bytes: bytes,
    duration: float,
    bpm: int,
    ecc_level: int = ECC_RS_255_120,
) -> bytes:
    manifest = bytearray(48)
    manifest[0] = MANIFEST_VERSION
    manifest[1] = lut_id
    manifest[2] = ecc_level
    manifest[3:5] = len(fingerprint_bytes).to_bytes(2, "big")
    manifest[5:9] = struct.pack(">f", float(duration))
    manifest[9:11] = int(bpm).to_bytes(2, "big")
    crc = zlib.crc32(fingerprint_bytes) & 0xFFFFFFFF
    manifest[11:15] = crc.to_bytes(4, "big")
    return bytes(manifest)


def _parse_manifest(manifest_bytes: bytes) -> dict[str, Any]:
    return {
        "version": manifest_bytes[0],
        "lut_id": manifest_bytes[1],
        "ecc_level": manifest_bytes[2],
        "fingerprint_len": int.from_bytes(manifest_bytes[3:5], "big"),
        "duration": struct.unpack(">f", manifest_bytes[5:9])[0],
        "bpm": int.from_bytes(manifest_bytes[9:11], "big"),
        "stored_crc": int.from_bytes(manifest_bytes[11:15], "big"),
    }


def _assemble_stream(
    fingerprint_bytes: bytes,
    waveform_values: list[float],
) -> bytearray:
    data_bytes, parity_bytes = _rs_encode(fingerprint_bytes)
    wf = bytes(max(0, min(255, round(v * 255))) for v in waveform_values[:128])
    if len(wf) < 128:
        wf = wf + b"\x00" * (128 - len(wf))
    waveform_rgb = _triplicate(wf)
    padding = _build_padding(fingerprint_bytes)

    stream = bytearray()
    stream += _triplicate(data_bytes)
    stream += _triplicate(parity_bytes)
    stream += waveform_rgb
    stream += padding
    assert len(stream) == STREAM_BYTES
    return stream


def _render_glyph_image(
    stream: bytearray,
    manifest_bytes: bytes,
    lut_name: str,
) -> Image.Image:
    img = Image.new("RGB", (GLYPH_SIZE, GLYPH_SIZE), (0, 0, 0))
    pixels = img.load()

    for i, (row, col) in enumerate(_SPIRAL_COORDS):
        r_raw = stream[i * 3]
        g_raw = stream[i * 3 + 1]
        b_raw = stream[i * 3 + 2]
        pixels[col, row] = apply_lut(r_raw, g_raw, b_raw, lut_name)

    for i, (row, col) in enumerate(_MANIFEST_COORDS):
        base = i * 3
        pixels[col, row] = (
            manifest_bytes[base],
            manifest_bytes[base + 1],
            manifest_bytes[base + 2],
        )

    return img


def _read_manifest_from_image(pixels) -> bytes:
    manifest = bytearray()
    for row, col in _MANIFEST_COORDS:
        r, g, b = pixels[col, row]
        manifest.extend((r, g, b))
    return bytes(manifest)


def _read_stream_from_image(pixels, lut_id: int) -> bytearray:
    stream = bytearray()
    for row, col in _SPIRAL_COORDS:
        r_tone, g_tone, b_tone = pixels[col, row]
        r_raw, g_raw, b_raw = invert_lut(r_tone, g_tone, b_tone, lut_id)
        stream.extend((r_raw, g_raw, b_raw))
    return stream


# --- Visual layer: Julia set + domain warp -----------------------------------
#
# Encoded data lives in the R channel of every spiral pixel (after LUT
# tone-mapping). The visual layer adds aesthetic detail by modulating G and B
# only; R is left untouched, so decode is unaffected. The manifest pixels are
# raw bytes (no LUT) and must also be left untouched.

_JULIA_MAX_ITER = 120
_JULIA_ESCAPE_R2 = 4.0
_JULIA_ZOOM = 1.5

# Boolean (size, size) masks marking which pixels belong to the spiral region.
_SPIRAL_MASK_64 = np.zeros((GLYPH_SIZE, GLYPH_SIZE), dtype=bool)
for _row, _col in _SPIRAL_COORDS:
    _SPIRAL_MASK_64[_row, _col] = True


def _julia_c_from_bytes(fingerprint_bytes: bytes) -> tuple[float, float]:
    """Derive a Julia ``c`` parameter from the fingerprint header bytes.

    Bytes 0–3 are read as two big-endian uint16 values mapped to ``[-0.8, 0.8]``.
    The radius is then clamped into the visually interesting band
    ``|c| ∈ [0.3, 0.75]`` while preserving the original angle.
    """
    cx = (int.from_bytes(fingerprint_bytes[0:2], "big") / 65535.0) * 1.6 - 0.8
    cy = (int.from_bytes(fingerprint_bytes[2:4], "big") / 65535.0) * 1.6 - 0.8
    r = math.sqrt(cx * cx + cy * cy)
    if r < 0.3 or r > 0.75:
        target_r = 0.52
        if r == 0:
            cx, cy = target_r, 0.0
        else:
            cx = cx / r * target_r
            cy = cy / r * target_r
    return cx, cy


def _julia_field(fingerprint_bytes: bytes, size: int = 64) -> np.ndarray:
    """Vectorized Julia set escape-time field, normalized to ``[0, 1]``."""
    cx, cy = _julia_c_from_bytes(fingerprint_bytes)

    axis = np.linspace(-_JULIA_ZOOM, _JULIA_ZOOM, size, dtype=np.float64)
    zr = np.tile(axis.reshape(1, size), (size, 1))
    zi = np.tile(axis.reshape(size, 1), (1, size))

    escaped = np.zeros((size, size), dtype=bool)
    smooth = np.zeros((size, size), dtype=np.float64)

    for i in range(_JULIA_MAX_ITER):
        mag2 = zr * zr + zi * zi
        new_escape = (~escaped) & (mag2 > _JULIA_ESCAPE_R2)
        if new_escape.any():
            mag = np.sqrt(mag2[new_escape])
            log_mag = np.log2(np.maximum(np.log2(mag), 1e-12))
            smooth[new_escape] = i + 1 - log_mag
            escaped |= new_escape

        if escaped.all():
            break

        active = ~escaped
        tmp_r = zr * zr - zi * zi + cx
        tmp_i = 2.0 * zr * zi + cy
        zr = np.where(active, tmp_r, zr)
        zi = np.where(active, tmp_i, zi)

    return np.clip(smooth / _JULIA_MAX_ITER, 0.0, 1.0).astype(np.float32)


def _domain_warp(
    field: np.ndarray, waveform: list[float], amp_scale: float = 1.0
) -> np.ndarray:
    """Warp ``field`` with two orthogonal sine displacements driven by waveform."""
    size = field.shape[0]
    wf = list(waveform) + [0.0] * max(0, 5 - len(waveform))

    f1 = 0.06 + wf[0] * 0.10
    f2 = 0.06 + wf[1] * 0.10
    p1 = wf[2] * 2.0 * math.pi
    p2 = wf[3] * 2.0 * math.pi
    amp = (4.0 + wf[4] * 8.0) * amp_scale

    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    wx = xs + amp * np.sin(f1 * ys + p1)
    wy = ys + amp * np.sin(f2 * xs + p2)

    warped = map_coordinates(
        field.astype(np.float64), [wy, wx], order=1, mode="wrap"
    )
    return np.clip(warped, 0.0, 1.0).astype(np.float32)


def _apply_visual_layer(
    raw_img: Image.Image,
    warped: np.ndarray,
    lut_name: str | None = None,  # unused; kept for spec parity
) -> Image.Image:
    """Multiply-blend ``warped`` into the G and B channels of spiral pixels only.

    The R channel and every manifest pixel are left untouched so that the
    encoded data and micro-manifest survive a roundtrip through decode.
    """
    if raw_img.size != (GLYPH_SIZE, GLYPH_SIZE):
        raise ValueError("Visual layer expects a 64×64 image")

    arr = np.array(raw_img, dtype=np.uint8).copy()
    jv = warped.astype(np.float32)

    g = arr[..., 1].astype(np.float32) * (0.6 + 0.8 * jv)
    b = arr[..., 2].astype(np.float32) * (0.4 + 1.2 * jv)
    g = np.clip(g, 0, 255).astype(np.uint8)
    b = np.clip(b, 0, 255).astype(np.uint8)

    mask = _SPIRAL_MASK_64
    arr[..., 1] = np.where(mask, g, arr[..., 1])
    arr[..., 2] = np.where(mask, b, arr[..., 2])
    return Image.fromarray(arr, mode="RGB")


def _ensure_png_path(output_path: str) -> None:
    if not output_path.lower().endswith(".png"):
        raise ValueError("Glyph must be saved as PNG; JPEG will corrupt pixel data")


# --- Public API -------------------------------------------------------------


def list_luts() -> list[str]:
    """Return available LUT names."""
    return list(LUT_NAMES)


def render_glyph_image(
    mp3_path: str,
    lut_name: str = "magma",
    fingerprint_data: dict | None = None,
    bpm: int = 0,
) -> Image.Image:
    """Build a decodable 64×64 glyph ``Image`` in memory (no file I/O).

    The image is rendered at the native 64×64 spiral grid and then has a
    Julia + domain-warp visual layer multiplied into the G and B channels of
    the spiral region. The R channel and the micro-manifest corner are left
    untouched, so the encoded fingerprint bytes survive a decode roundtrip.
    """
    if lut_name not in _LUT_ID:
        raise ValueError(f"Unknown LUT {lut_name!r}. Choose from {list_luts()}.")

    if fingerprint_data is None:
        fingerprint_data = generate_fingerprint(mp3_path)

    fingerprint_bytes = fingerprint_data["fingerprint_bytes"]
    if len(fingerprint_bytes) != FINGERPRINT_BYTE_LEN:
        raise ValueError(
            f"Expected {FINGERPRINT_BYTE_LEN}-byte fingerprint, got {len(fingerprint_bytes)}"
        )

    waveform = get_rms_envelope(mp3_path, n_frames=128)
    stream = _assemble_stream(fingerprint_bytes, waveform)
    manifest = _build_manifest_bytes(
        _LUT_ID[lut_name],
        fingerprint_bytes,
        fingerprint_data["duration"],
        bpm,
    )
    img = _render_glyph_image(stream, manifest, lut_name)

    julia = _julia_field(fingerprint_bytes, size=GLYPH_SIZE)
    warped = _domain_warp(julia, waveform, amp_scale=1.0)
    return _apply_visual_layer(img, warped, lut_name)


def render_glyph_display(
    mp3_path: str,
    lut_name: str = "magma",
    fingerprint_data: dict | None = None,
    bpm: int = 0,
) -> Image.Image:
    """Render a 256×256 Julia + domain-warp glyph at native resolution.

    Display-only — no spiral data, no micro-manifest, no Reed–Solomon. The
    returned image cannot be decoded back into a fingerprint; pass the 64×64
    version produced by :func:`render_glyph_image` or :func:`generate_glyph`
    to :func:`decode_glyph` for that.
    """
    del bpm  # display-only: no manifest, BPM has no slot
    if lut_name not in _LUT_ID:
        raise ValueError(f"Unknown LUT {lut_name!r}. Choose from {list_luts()}.")

    if fingerprint_data is None:
        fingerprint_data = generate_fingerprint(mp3_path)

    fingerprint_bytes = fingerprint_data["fingerprint_bytes"]
    waveform = get_rms_envelope(mp3_path, n_frames=128)

    julia = _julia_field(fingerprint_bytes, size=256)
    warped = _domain_warp(julia, waveform, amp_scale=4.0)

    lut = _LUT_FORWARD[lut_name]
    idx = np.clip(np.round(warped * 255.0), 0, 255).astype(np.uint8)
    r = lut["R"][idx]
    g = lut["G"][idx]
    b = lut["B"][idx]
    rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")


def generate_glyph(
    mp3_path: str,
    output_path: str,
    lut_name: str = "magma",
    also_save_display: bool = True,
) -> dict:
    """Full encode pipeline — fingerprint MP3 and write a 64×64 glyph PNG."""
    _ensure_png_path(output_path)

    fingerprint_data = generate_fingerprint(mp3_path)
    meta = read_metadata(mp3_path)
    bpm = 0
    if meta.get("bpm"):
        try:
            bpm = int(float(meta["bpm"]))
        except (TypeError, ValueError):
            bpm = 0

    fingerprint_bytes = fingerprint_data["fingerprint_bytes"]
    img = render_glyph_image(mp3_path, lut_name, fingerprint_data, bpm=bpm)
    img.save(output_path, format="PNG", optimize=False)

    crc = zlib.crc32(fingerprint_bytes) & 0xFFFFFFFF
    result: dict[str, Any] = {
        "glyph_path": output_path,
        "fingerprint_hex": fingerprint_bytes.hex(),
        "duration": fingerprint_data["duration"],
        "lut_name": lut_name,
        "crc32": f"{crc:08x}",
    }

    if also_save_display:
        display_path = output_path.replace(".png", "_256.png")
        if display_path == output_path:
            display_path = output_path[:-4] + "_256.png"
        img.resize((256, 256), Image.NEAREST).save(display_path, format="PNG", optimize=False)
        result["display_path"] = display_path

    return result


def decode_glyph(png_path: str) -> dict:
    """Decode a 64×64 glyph PNG into fingerprint bytes and metadata."""
    if not png_path.lower().endswith(".png"):
        raise ValueError("Glyph must be saved as PNG; JPEG will corrupt pixel data")

    img = Image.open(png_path).convert("RGB")
    if img.size != (GLYPH_SIZE, GLYPH_SIZE):
        raise ValueError(f"Glyph must be exactly {GLYPH_SIZE}×{GLYPH_SIZE} pixels")

    pixels = img.load()
    manifest_bytes = _read_manifest_from_image(pixels)
    info = _parse_manifest(manifest_bytes)

    lut_id = info["lut_id"]
    if lut_id not in _LUT_INVERSE:
        raise ValueError(f"Unknown lut_id {lut_id} in manifest")

    raw_stream = _read_stream_from_image(pixels, lut_id)
    data_bytes = _extract_triplicated(raw_stream, 0, FINGERPRINT_BYTE_LEN)
    parity_bytes = _extract_triplicated(raw_stream, FP_SEGMENT_PIXELS, FINGERPRINT_BYTE_LEN)

    ecc_corrections = 0
    if info["ecc_level"] == ECC_RS_255_120:
        fingerprint_bytes, ecc_corrections = _rs_decode(data_bytes, parity_bytes)
    elif info["ecc_level"] == 0:
        fingerprint_bytes = data_bytes[:FINGERPRINT_BYTE_LEN]
    else:
        fingerprint_bytes, ecc_corrections = _rs_decode(data_bytes, parity_bytes)

    computed_crc = zlib.crc32(fingerprint_bytes) & 0xFFFFFFFF
    crc_match = computed_crc == info["stored_crc"]

    lut_name = LUT_NAMES[lut_id] if lut_id < len(LUT_NAMES) else f"unknown({lut_id})"

    return {
        "fingerprint_bytes": fingerprint_bytes,
        "fingerprint_hex": fingerprint_bytes.hex(),
        "duration": info["duration"],
        "bpm": info["bpm"],
        "lut_name": lut_name,
        "verified": crc_match,
        "crc_match": crc_match,
        "ecc_corrections": ecc_corrections,
        "rs_recovered": True,
    }


def verify_glyph_against_mp3(png_path: str, mp3_path: str) -> dict:
    """Decode a glyph and compare against a freshly computed MP3 fingerprint."""
    decoded = decode_glyph(png_path)
    live = generate_fingerprint(mp3_path)

    live_bytes = live["fingerprint_bytes"]
    decoded_bytes = decoded["fingerprint_bytes"]
    bytes_match = live_bytes == decoded_bytes

    live_crc = zlib.crc32(live_bytes) & 0xFFFFFFFF
    decoded_crc = zlib.crc32(decoded_bytes) & 0xFFFFFFFF
    crc_match = live_crc == decoded_crc

    return {
        "match": bytes_match and crc_match,
        "crc_match": crc_match,
        "bytes_match": bytes_match,
        "decoded": decoded,
        "live": {
            "fingerprint_hex": live_bytes.hex(),
            "fingerprint_hash": live["fingerprint_hash"],
            "duration": live["duration"],
            "crc32": f"{live_crc:08x}",
        },
    }
