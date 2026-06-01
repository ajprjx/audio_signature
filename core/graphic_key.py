"""QR + waveform compositing into a styled PNG graphic key, and QR decoding."""

from __future__ import annotations

import base64
import json
import zlib
from datetime import datetime, timezone

import qrcode
from PIL import Image, ImageDraw, ImageFont

try:
    from qrcode.exceptions import DataOverflowError
except ImportError:  # pragma: no cover - older qrcode
    DataOverflowError = ValueError

# Compressed-payload marker so the decoder can tell zlib payloads from the
# legacy plain-base64 ones.
_ZLIB_PREFIX = "Z1:"

# Error-correction levels tried in order. The QR sits beside the waveform (not
# under it), so we don't strictly need level H; we start high and fall back to
# lower redundancy / higher capacity only when a large fingerprint demands it.
_EC_LEVELS = [
    qrcode.constants.ERROR_CORRECT_H,
    qrcode.constants.ERROR_CORRECT_Q,
    qrcode.constants.ERROR_CORRECT_M,
    qrcode.constants.ERROR_CORRECT_L,
]

from .waveform import generate_waveform_image, _hex_to_rgb

# --- Layout constants -------------------------------------------------------

CANVAS_W, CANVAS_H = 600, 300
BG_COLOR = "#0A0A0A"
SEPARATOR_COLOR = "#333333"
TEXT_COLOR = "#FFFFFF"
SUBTEXT_COLOR = "#AAAAAA"
WAVE_FG = "#00FFAA"

QR_SIZE = 220
WAVE_W, WAVE_H = 260, 160

HEADER_H = 56
FOOTER_H = 30


# --- Fonts ------------------------------------------------------------------

_MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Andale Mono.ttf",
]


def _load_font(size: int, bold: bool = False):
    """Load a monospace TTF at the given size, falling back to the default."""
    candidates = list(_MONO_CANDIDATES)
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# --- Payload helpers --------------------------------------------------------


def _build_payload(metadata: dict, fingerprint_data: dict) -> dict:
    return {
        "v": 1,
        "title": metadata.get("title", "Unknown Title"),
        "artist": metadata.get("artist", "Unknown Artist"),
        "duration": fingerprint_data.get("duration", metadata.get("duration", 0.0)),
        "fp_hash": fingerprint_data.get("fingerprint_hash", ""),
        "fingerprint": fingerprint_data.get("fingerprint", ""),
        "ts": metadata.get("timestamp")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _encode_payload(payload: dict) -> str:
    """Serialize a payload to a zlib-compressed, base64, marker-prefixed string."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    compressed = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
    return _ZLIB_PREFIX + compressed


def _qr_image_for(data: str) -> Image.Image | None:
    """Build the smallest QR that fits ``data``, trying decreasing EC levels.

    Returns None if the data won't fit even at the lowest error correction
    (i.e. it exceeds QR version 40 capacity).
    """
    for ec in _EC_LEVELS:
        qr = qrcode.QRCode(
            version=None,  # auto-size to fit the payload
            error_correction=ec,
            box_size=10,
            border=2,
        )
        qr.add_data(data)
        try:
            qr.make(fit=True)
        except (DataOverflowError, ValueError):
            # Too big for this EC level (or overflowed version 40); try lower.
            continue
        img = qr.make_image(fill_color="white", back_color=BG_COLOR).convert("RGB")
        return img.resize((QR_SIZE, QR_SIZE), Image.NEAREST)
    return None


def _make_qr(payload: dict) -> Image.Image:
    """Encode the payload into a QR image, degrading gracefully if oversized.

    First tries the full payload (compressed). If even the lowest error
    correction can't hold it, falls back to a compact payload that drops the
    full fingerprint string (the fingerprint hash and metadata are retained),
    so encoding never crashes on long fingerprints.
    """
    img = _qr_image_for(_encode_payload(payload))
    if img is not None:
        return img

    # Fallback: keep identity + metadata, drop the bulky fingerprint string.
    compact = dict(payload)
    compact["fingerprint"] = ""
    compact["fp_truncated"] = True
    img = _qr_image_for(_encode_payload(compact))
    if img is not None:
        return img

    raise ValueError(
        "QR payload too large to encode even without the fingerprint. "
        "Reduce the fingerprint window (max_seconds) further."
    )


# --- Public API -------------------------------------------------------------


def build_graphic_key(
    mp3_path: str,
    output_png_path: str,
    metadata: dict,
    fingerprint_data: dict,
) -> str:
    """Compose the final 600x300 graphic key PNG and write it to disk."""
    payload = _build_payload(metadata, fingerprint_data)

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), _hex_to_rgb(BG_COLOR))
    draw = ImageDraw.Draw(canvas)

    title_font = _load_font(20)
    sub_font = _load_font(14)
    footer_font = _load_font(11)

    # --- Header text ---
    title = payload["title"]
    sub = f"{payload['artist']} · {_format_duration(payload['duration'])}"

    tw, _ = _text_size(draw, title, title_font)
    draw.text(((CANVAS_W - tw) / 2, 8), title, font=title_font, fill=TEXT_COLOR)
    sw, _ = _text_size(draw, sub, sub_font)
    draw.text(((CANVAS_W - sw) / 2, 32), sub, font=sub_font, fill=SUBTEXT_COLOR)

    # --- Body region between header and footer ---
    body_top = HEADER_H
    body_bottom = CANVAS_H - FOOTER_H
    body_h = body_bottom - body_top
    mid_x = CANVAS_W // 2

    # QR code centered in the left panel.
    qr_img = _make_qr(payload)
    qr_x = (mid_x - QR_SIZE) // 2
    qr_y = body_top + (body_h - QR_SIZE) // 2
    canvas.paste(qr_img, (qr_x, qr_y))

    # Separator line between QR and waveform panels.
    draw.line(
        [(mid_x, body_top + 6), (mid_x, body_bottom - 6)],
        fill=_hex_to_rgb(SEPARATOR_COLOR),
        width=1,
    )

    # Waveform centered in the right panel — strictly NOT overlapping the QR.
    try:
        wave_img = generate_waveform_image(
            mp3_path, width=WAVE_W, height=WAVE_H, color_fg=WAVE_FG, color_bg=BG_COLOR
        )
    except Exception:
        wave_img = Image.new("RGB", (WAVE_W, WAVE_H), _hex_to_rgb(BG_COLOR))
    wave_x = mid_x + ((CANVAS_W - mid_x) - WAVE_W) // 2
    wave_y = body_top + (body_h - WAVE_H) // 2
    canvas.paste(wave_img, (wave_x, wave_y))

    # --- Footer ---
    footer = f"{payload['fp_hash']}   [{payload['ts']}]"
    fw, _ = _text_size(draw, footer, footer_font)
    draw.text(
        ((CANVAS_W - fw) / 2, body_bottom + 8),
        footer,
        font=footer_font,
        fill=SUBTEXT_COLOR,
    )

    canvas.save(output_png_path, "PNG")
    return output_png_path


def _format_duration(seconds: float) -> str:
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?:??"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def _decode_qr(png_path: str) -> str:
    """Return the raw decoded text of the first QR found in the image.

    Tries pyzbar first (needs libzbar0), then zxing-cpp as a pure-python
    fallback. Raises ValueError if neither finds a QR.
    """
    img = Image.open(png_path).convert("RGB")

    # Attempt 1: pyzbar
    try:
        from pyzbar.pyzbar import decode as zbar_decode

        results = zbar_decode(img)
        if results:
            return results[0].data.decode("utf-8")
    except Exception:
        pass

    # Attempt 2: zxing-cpp
    try:
        import zxingcpp

        result = zxingcpp.read_barcode(img)
        if result is not None and result.text:
            return result.text
    except Exception:
        pass

    raise ValueError(
        "Could not decode a QR code from the image. Ensure a QR scanner backend "
        "is installed: `pip install pyzbar` (needs libzbar0) or "
        "`pip install zxing-cpp`."
    )


def load_graphic_key_payload(png_path: str) -> dict:
    """Decode a graphic key PNG back into its payload dict.

    Handles both the zlib-compressed payload format (``Z1:`` prefix) and the
    legacy plain-base64 format.
    """
    raw_text = _decode_qr(png_path)
    if raw_text.startswith(_ZLIB_PREFIX):
        decoded = zlib.decompress(base64.b64decode(raw_text[len(_ZLIB_PREFIX):]))
    else:
        decoded = base64.b64decode(raw_text)
    return json.loads(decoded.decode("utf-8"))
