"""RMS waveform envelope extraction via librosa."""

from __future__ import annotations

import numpy as np

try:
    import librosa
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "librosa is required. Install with `pip install librosa soundfile`."
    ) from exc


def get_rms_envelope(mp3_path: str, n_frames: int = 128) -> list[float]:
    """Return an ``n_frames`` length RMS envelope as floats in 0.0–1.0."""
    return compute_rms_envelope(mp3_path, n_frames).tolist()


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
