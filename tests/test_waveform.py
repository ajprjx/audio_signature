"""Tests for core.waveform."""

from __future__ import annotations

import numpy as np

from core.waveform import (
    _hex_to_rgb,
    compute_rms_envelope,
    generate_waveform_image,
    get_rms_envelope,
)


def test_hex_to_rgb():
    assert _hex_to_rgb("#000000") == (0, 0, 0)
    assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert _hex_to_rgb("00FFAA") == (0, 255, 170)


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


def test_generate_waveform_image_dims(sample_mp3):
    img = generate_waveform_image(sample_mp3, width=200, height=80)
    assert img.size == (200, 80)
    assert img.mode == "RGB"


def test_generate_waveform_image_uses_foreground_color(sample_mp3):
    img = generate_waveform_image(
        sample_mp3, width=120, height=60, color_fg="#FF00FF", color_bg="#000000"
    )
    arr = np.array(img)
    # The neon foreground should appear somewhere in the rendered bars.
    # Use a tolerance because LANCZOS downscale anti-aliases the edges.
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    fg_like = (r > 200) & (g < 60) & (b > 200)
    assert fg_like.any(), "Expected some near-foreground pixels in the waveform"
