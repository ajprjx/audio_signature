"""Decode and verify pipelines for graphic keys."""

from __future__ import annotations

from . import metadata as metadata_mod
from .fingerprint import (
    fingerprint_similarity,
    fingerprints_match,
    generate_fingerprint,
)
from .graphic_key import load_graphic_key_payload


def decode_graphic_key(png_path: str) -> dict:
    """Decode a graphic key PNG into a structured result dict."""
    payload = load_graphic_key_payload(png_path)
    return {
        "title": payload.get("title"),
        "artist": payload.get("artist"),
        "duration": payload.get("duration"),
        "fingerprint_hash": payload.get("fp_hash"),
        "fingerprint": payload.get("fingerprint"),
        "generated_at": payload.get("ts"),
        "verified": True,  # QR decoded successfully
    }


def verify_against_mp3(png_path: str, mp3_path: str, threshold: float = 0.85) -> dict:
    """Decode a graphic key, re-fingerprint the MP3, and compare them."""
    key = decode_graphic_key(png_path)
    fresh = generate_fingerprint(mp3_path)
    mp3_meta = metadata_mod.read_metadata(mp3_path)

    key_fp = key.get("fingerprint") or ""
    fresh_fp = fresh.get("fingerprint") or ""

    if key_fp and fresh_fp:
        similarity = fingerprint_similarity(key_fp, fresh_fp)
        match = fingerprints_match(key_fp, fresh_fp, threshold=threshold)
    else:
        # Fall back to comparing the short hashes when fingerprints are absent.
        match = key.get("fingerprint_hash") == fresh.get("fingerprint_hash")
        similarity = 1.0 if match else 0.0

    return {
        "match": bool(match),
        "similarity": round(float(similarity), 4),
        "key_metadata": key,
        "mp3_metadata": mp3_meta,
    }
