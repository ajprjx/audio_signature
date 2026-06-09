"""Tests for core.fingerprint helpers."""

from __future__ import annotations

import pytest

from core.fingerprint import (
    FINGERPRINT_BYTE_LEN,
    FingerprintError,
    fingerprint_similarity,
    fingerprint_to_bytes,
    fingerprints_match,
    generate_fingerprint,
)


def test_fingerprint_to_bytes_is_fixed_width():
    assert len(fingerprint_to_bytes("AQAA")) == FINGERPRINT_BYTE_LEN
    assert len(fingerprint_to_bytes("AQAA" * 1000)) == FINGERPRINT_BYTE_LEN


def test_fingerprint_to_bytes_is_deterministic():
    a = fingerprint_to_bytes("AQAA_test_value_123")
    b = fingerprint_to_bytes("AQAA_test_value_123")
    assert a == b


def test_fingerprint_to_bytes_differs_for_different_inputs():
    a = fingerprint_to_bytes("AQAA_one")
    b = fingerprint_to_bytes("AQAA_two")
    assert a != b


def test_fingerprint_similarity_self_is_one():
    fp = "AQAAQ_some_fingerprint_string"
    assert fingerprint_similarity(fp, fp) == 1.0


def test_fingerprint_similarity_empty_is_zero():
    assert fingerprint_similarity("", "AQAA") == 0.0
    assert fingerprint_similarity("AQAA", "") == 0.0


def test_fingerprints_match_threshold_behaviour():
    # Identical fingerprints always match.
    fp = "AQABZ123"
    assert fingerprints_match(fp, fp, threshold=0.85)

    # Wildly different fingerprints should fail at the production threshold.
    assert not fingerprints_match("AQAA" * 4, "ZZZZZ" * 4, threshold=0.85)


def test_generate_fingerprint_shape(sample_mp3, require_fpcalc):
    data = generate_fingerprint(sample_mp3)
    assert set(data) == {"fingerprint", "fingerprint_bytes", "duration", "fingerprint_hash"}
    assert isinstance(data["fingerprint"], str) and data["fingerprint"]
    assert len(data["fingerprint_bytes"]) == FINGERPRINT_BYTE_LEN
    assert len(data["fingerprint_hash"]) == 16
    assert data["duration"] > 0


def test_generate_fingerprint_deterministic(sample_mp3, require_fpcalc):
    a = generate_fingerprint(sample_mp3)
    b = generate_fingerprint(sample_mp3)
    assert a["fingerprint"] == b["fingerprint"]
    assert a["fingerprint_bytes"] == b["fingerprint_bytes"]
    assert a["fingerprint_hash"] == b["fingerprint_hash"]


def test_generate_fingerprint_missing_file_raises(require_fpcalc):
    with pytest.raises(FingerprintError):
        generate_fingerprint("/nonexistent/does_not_exist.mp3")


def test_generate_fingerprint_distinct_audio_distinct_hash(
    sample_mp3, sample_mp3_alt, require_fpcalc
):
    a = generate_fingerprint(sample_mp3)
    b = generate_fingerprint(sample_mp3_alt)
    assert a["fingerprint_hash"] != b["fingerprint_hash"]
    assert a["fingerprint_bytes"] != b["fingerprint_bytes"]
    # Hamming similarity between sweep and noise should be well below match threshold.
    assert fingerprint_similarity(a["fingerprint"], b["fingerprint"]) < 0.85
