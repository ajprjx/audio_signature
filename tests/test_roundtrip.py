"""Full encode -> decode -> verify roundtrip test.

Generates a synthetic MP3 from a sine wave so the test is self-contained and
requires no network access. Skips gracefully when system binaries (fpcalc) or
QR-decoding backends are unavailable.
"""

from __future__ import annotations

import os
import shutil

import numpy as np
import pytest

from core.decoder import decode_graphic_key, verify_against_mp3
from core.fingerprint import generate_fingerprint
from core.graphic_key import build_graphic_key
from core.metadata import read_signature_tag, write_signature_tag

SAMPLE_RATE = 44100
DURATION_SEC = 8


def _qr_backend_available() -> bool:
    try:
        import pyzbar.pyzbar  # noqa: F401

        return True
    except Exception:
        pass
    try:
        import zxingcpp  # noqa: F401

        return True
    except Exception:
        pass
    return False


@pytest.fixture()
def sample_mp3(tmp_path):
    """Create a short MP3 of a frequency-sweeping sine wave."""
    soundfile = pytest.importorskip("soundfile")

    if shutil.which("ffmpeg") is None and shutil.which("lame") is None:
        pytest.skip("ffmpeg/lame required to encode the sample MP3")

    t = np.linspace(0, DURATION_SEC, SAMPLE_RATE * DURATION_SEC, endpoint=False)
    # A sweep so the fingerprint and waveform have real structure.
    freq = np.linspace(220, 880, t.size)
    signal = 0.5 * np.sin(2 * np.pi * freq * t).astype(np.float32)

    wav_path = tmp_path / "sample.wav"
    soundfile.write(str(wav_path), signal, SAMPLE_RATE)

    mp3_path = tmp_path / "sample.mp3"
    # Convert via ffmpeg if available.
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


def test_full_roundtrip(sample_mp3, tmp_path):
    if shutil.which("fpcalc") is None:
        pytest.skip("fpcalc (libchromaprint-tools) not installed")
    if not _qr_backend_available():
        pytest.skip("No QR decode backend (pyzbar or zxing-cpp) installed")

    # 1. Encode pipeline.
    fingerprint_data = generate_fingerprint(sample_mp3)
    original_hash = fingerprint_data["fingerprint_hash"]

    signature_payload = {
        "fingerprint_hash": original_hash,
        "duration": fingerprint_data["duration"],
        "title": "Test Sweep",
        "artist": "pytest",
        "timestamp": "2024-01-15T10:30:00Z",
    }
    write_signature_tag(sample_mp3, signature_payload)

    # 2. Confirm the ID3 tag round-trips.
    tag = read_signature_tag(sample_mp3)
    assert tag is not None
    assert tag["fingerprint_hash"] == original_hash

    # 3. Build the graphic key.
    out_png = str(tmp_path / "key.png")
    metadata = {
        "title": "Test Sweep",
        "artist": "pytest",
        "timestamp": "2024-01-15T10:30:00Z",
    }
    build_graphic_key(sample_mp3, out_png, metadata, fingerprint_data)
    assert os.path.exists(out_png)

    # 4. Decode the PNG.
    decoded = decode_graphic_key(out_png)
    assert decoded["verified"] is True
    assert decoded["fingerprint_hash"] == original_hash
    assert decoded["title"] == "Test Sweep"

    # 5. Verify the MP3 against its key.
    result = verify_against_mp3(out_png, sample_mp3)
    assert result["match"] is True
    assert result["similarity"] >= 0.85
