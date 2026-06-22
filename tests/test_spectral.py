"""Feature 1: spectral codec — lossless bytes <-> smooth 256x256 RGB field."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from core import spectral


def _payload(n, seed=0):
    return np.random.default_rng(seed).integers(0, 256, n, dtype=np.uint8).tobytes()


def test_round_trips_a_payload():
    payload = _payload(200)
    img = spectral.encode_field(payload)
    assert spectral.decode_field(img) == payload


def test_survives_png_save_and_reload():
    payload = _payload(200, seed=1)
    buf = io.BytesIO()
    spectral.encode_field(payload).save(buf, format="PNG")
    buf.seek(0)
    assert spectral.decode_field(Image.open(buf)) == payload


def test_output_is_256x256_rgb():
    img = spectral.encode_field(_payload(50))
    assert img.size == (256, 256)
    assert img.mode == "RGB"


def test_capacity_is_at_least_200_bytes():
    assert spectral.CAPACITY_BYTES >= 200


@pytest.mark.parametrize("n", [0, 1, 32, 128, None])  # None -> exactly capacity
def test_round_trips_across_sizes(n):
    n = spectral.CAPACITY_BYTES if n is None else n
    payload = _payload(n, seed=n + 3)
    assert spectral.decode_field(spectral.encode_field(payload)) == payload


def test_round_trips_many_random_payloads_at_ber_zero():
    for seed in range(25):
        payload = _payload(spectral.CAPACITY_BYTES, seed=seed)
        assert spectral.decode_field(spectral.encode_field(payload)) == payload


def test_rejects_oversized_payload():
    with pytest.raises(ValueError):
        spectral.encode_field(_payload(spectral.CAPACITY_BYTES + 1))


def test_field_is_smooth():
    arr = np.asarray(spectral.encode_field(_payload(spectral.CAPACITY_BYTES)), float)
    # A smooth gradient has small neighbour differences (no per-pixel static).
    grad = np.abs(np.diff(arr, axis=0)).mean() + np.abs(np.diff(arr, axis=1)).mean()
    assert grad < 6.0


def test_distinct_payloads_yield_distinct_fields():
    a = np.asarray(spectral.encode_field(_payload(100, seed=1)))
    b = np.asarray(spectral.encode_field(_payload(100, seed=2)))
    assert not np.array_equal(a, b)
