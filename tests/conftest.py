"""Shared pytest fixtures.

Provides a synthetic ``sample_mp3`` (10s sine sweep) that the rest of the suite
builds on, plus a small set of derived fixtures (a generated pixel glyph PNG and
a fingerprint payload) so individual tests don't each re-run the fingerprint
pipeline.
"""

from __future__ import annotations

import os
import shutil

import numpy as np
import pytest

SAMPLE_RATE = 44100
DURATION_SEC = 10


@pytest.fixture()
def sample_mp3(tmp_path):
    """Create a short MP3 of a frequency-sweeping sine wave."""
    soundfile = pytest.importorskip("soundfile")

    if shutil.which("ffmpeg") is None and shutil.which("lame") is None:
        pytest.skip("ffmpeg/lame required to encode the sample MP3")

    t = np.linspace(0, DURATION_SEC, SAMPLE_RATE * DURATION_SEC, endpoint=False)
    freq = np.linspace(220, 880, t.size)
    signal = 0.5 * np.sin(2 * np.pi * freq * t).astype(np.float32)

    wav_path = tmp_path / "sample.wav"
    soundfile.write(str(wav_path), signal, SAMPLE_RATE)

    mp3_path = tmp_path / "sample.mp3"
    if shutil.which("ffmpeg"):
        rc = os.system(
            f'ffmpeg -y -loglevel error -i "{wav_path}" "{mp3_path}"'
        )
        if rc != 0 or not mp3_path.exists():
            pytest.skip("ffmpeg failed to produce an MP3")
    else:
        rc = os.system(f'lame --silent "{wav_path}" "{mp3_path}"')
        if rc != 0 or not mp3_path.exists():
            pytest.skip("lame failed to produce an MP3")

    return str(mp3_path)


@pytest.fixture()
def sample_mp3_alt(tmp_path):
    """A second, acoustically distinct MP3 (white noise) for mismatch tests."""
    soundfile = pytest.importorskip("soundfile")
    if shutil.which("ffmpeg") is None and shutil.which("lame") is None:
        pytest.skip("ffmpeg/lame required to encode the sample MP3")

    rng = np.random.default_rng(42)
    signal = (0.5 * rng.standard_normal(SAMPLE_RATE * DURATION_SEC)).astype(np.float32)

    wav_path = tmp_path / "alt.wav"
    soundfile.write(str(wav_path), signal, SAMPLE_RATE)

    mp3_path = tmp_path / "alt.mp3"
    if shutil.which("ffmpeg"):
        rc = os.system(f'ffmpeg -y -loglevel error -i "{wav_path}" "{mp3_path}"')
    else:
        rc = os.system(f'lame --silent "{wav_path}" "{mp3_path}"')
    if rc != 0 or not mp3_path.exists():
        pytest.skip("audio encoder failed to produce an MP3")
    return str(mp3_path)


@pytest.fixture()
def require_fpcalc():
    if shutil.which("fpcalc") is None:
        pytest.skip("fpcalc (libchromaprint-tools) not installed")


@pytest.fixture()
def fingerprint_data(sample_mp3, require_fpcalc):
    from core.fingerprint import generate_fingerprint

    return generate_fingerprint(sample_mp3)


@pytest.fixture()
def glyph_png(tmp_path, sample_mp3, require_fpcalc):
    from core.pixel_glyph import generate_glyph

    out = str(tmp_path / "glyph.png")
    generate_glyph(sample_mp3, out, lut_name="magma", also_save_display=False)
    return out
