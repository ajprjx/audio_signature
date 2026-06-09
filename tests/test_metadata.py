"""Tests for core.metadata (ID3 read/write helpers)."""

from __future__ import annotations

from mutagen.id3 import ID3, TIT2, TPE1, TBPM

from core.metadata import (
    SIGNATURE_DESC,
    read_metadata,
    read_signature_tag,
    resolve_title,
    write_signature_tag,
)


def test_resolve_title_uses_metadata_title():
    assert resolve_title({"title": "Hello"}, "/tmp/anything.mp3") == "Hello"


def test_resolve_title_falls_back_to_filename():
    assert resolve_title({}, "/tmp/songs/my_song.mp3") == "my_song"


def test_resolve_title_prefers_original_filename_over_temp_path():
    meta = {"original_filename": "real_track.mp3"}
    assert resolve_title(meta, "/tmp/tmp9XYZ.mp3") == "real_track"


def test_resolve_title_blank_returns_unknown():
    assert resolve_title({}, "/") == "Unknown Title"


def test_signature_tag_roundtrip(sample_mp3):
    payload = {
        "fingerprint_hash": "deadbeefcafebabe",
        "duration": 12.3,
        "title": "Round Trip",
        "artist": "pytest",
        "timestamp": "2024-01-15T10:30:00Z",
    }
    write_signature_tag(sample_mp3, payload)

    decoded = read_signature_tag(sample_mp3)
    assert decoded == payload


def test_signature_tag_overwrites_previous(sample_mp3):
    write_signature_tag(sample_mp3, {"fingerprint_hash": "a" * 16})
    write_signature_tag(sample_mp3, {"fingerprint_hash": "b" * 16})

    tags = ID3(sample_mp3)
    frames = tags.getall(f"TXXX:{SIGNATURE_DESC}")
    assert len(frames) == 1
    assert read_signature_tag(sample_mp3)["fingerprint_hash"] == "b" * 16


def test_read_signature_tag_absent(sample_mp3):
    # Fresh MP3 from ffmpeg — no AudioSignature frame yet.
    assert read_signature_tag(sample_mp3) is None


def test_read_metadata_includes_duration_and_title(sample_mp3):
    tags = ID3(sample_mp3) if _has_id3(sample_mp3) else ID3()
    tags.add(TIT2(encoding=3, text=["Sweep"]))
    tags.add(TPE1(encoding=3, text=["pytester"]))
    tags.add(TBPM(encoding=3, text=["123"]))
    tags.save(sample_mp3)

    meta = read_metadata(sample_mp3)
    assert meta["title"] == "Sweep"
    assert meta["artist"] == "pytester"
    assert meta["bpm"] == "123"
    assert meta["duration"] > 0


def _has_id3(path: str) -> bool:
    from mutagen.id3 import ID3NoHeaderError

    try:
        ID3(path)
        return True
    except ID3NoHeaderError:
        return False
