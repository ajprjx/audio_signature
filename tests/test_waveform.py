"""Tests for core.waveform."""

from __future__ import annotations

import numpy as np

from core.waveform import (
    compute_rms_envelope,
    get_rms_envelope,
)


def test_get_rms_envelope_shape(sample_mp3):
    env = get_rms_envelope(sample_mp3, n_frames=128)
    assert isinstance(env, list)
    assert len(env) == 128
    assert all(0.0 <= v <= 1.0 for v in env)


def test_get_rms_envelope_custom_size(sample_mp3):
    env = get_rms_envelope(sample_mp3, n_frames=32)
    assert len(env) == 32


def test_compute_rms_envelope_peak_normalized(sample_mp3):
    env = compute_rms_envelope(sample_mp3, 64)
    assert env.dtype == np.float32
    # Peak should be normalized to 1.0 (sine sweep is not silent).
    assert np.isclose(env.max(), 1.0, atol=1e-6)
