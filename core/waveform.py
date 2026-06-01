"""Waveform image generation via librosa + Pillow."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

try:
    import librosa
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "librosa is required. Install with `pip install librosa soundfile`."
    ) from exc


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def compute_rms_envelope(mp3_path: str, n_bars: int) -> np.ndarray:
    """Load audio and return an ``n_bars`` length RMS envelope in 0..1."""
    y, sr = librosa.load(mp3_path, sr=None, mono=True)
    if y.size == 0:
        return np.zeros(n_bars, dtype=np.float32)

    # Compute frame-wise RMS, then resample down to exactly n_bars buckets.
    rms = librosa.feature.rms(y=y)[0]
    if rms.size == 0:
        return np.zeros(n_bars, dtype=np.float32)

    # Bucket the RMS frames into n_bars groups and take the max of each.
    idx = np.linspace(0, rms.size, n_bars + 1).astype(int)
    bars = np.array(
        [
            rms[idx[i] : max(idx[i] + 1, idx[i + 1])].max()
            for i in range(n_bars)
        ],
        dtype=np.float32,
    )

    peak = bars.max()
    if peak > 0:
        bars = bars / peak
    return bars


def generate_waveform_image(
    mp3_path: str,
    width: int = 400,
    height: int = 80,
    color_fg: str = "#00FFAA",
    color_bg: str = "#0A0A0A",
) -> Image.Image:
    """Render a symmetric (mirrored top/bottom) waveform bar chart.

    Bars are ~2px wide with a 1px gap, drawn on a dark background with a bright
    neon foreground. Rendered at 2x and downscaled for anti-aliased edges.
    """
    scale = 2
    w, h = width * scale, height * scale
    bar_w = 2 * scale
    gap = 1 * scale
    step = bar_w + gap
    n_bars = max(1, w // step)

    bars = compute_rms_envelope(mp3_path, n_bars)

    fg = _hex_to_rgb(color_fg)
    bg = _hex_to_rgb(color_bg)

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    mid = h / 2
    max_half = (h / 2) - scale  # small margin top/bottom

    for i, amp in enumerate(bars):
        x0 = i * step
        x1 = x0 + bar_w - 1
        bar_half = max(scale, amp * max_half)
        y0 = mid - bar_half
        y1 = mid + bar_half
        draw.rectangle([x0, y0, x1, y1], fill=fg)

    return img.resize((width, height), Image.LANCZOS)
