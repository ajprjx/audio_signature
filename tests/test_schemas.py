"""Tests for api.schemas upload validators."""

from __future__ import annotations

from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from api.schemas import (
    ValidationError,
    validate_audio_upload,
    validate_key_upload,
)


def _fs(filename: str, data: bytes = b"\x00") -> FileStorage:
    return FileStorage(stream=BytesIO(data), filename=filename)


def test_validate_audio_accepts_mp3():
    validate_audio_upload(_fs("song.mp3"))
    validate_audio_upload(_fs("Track Name.MP3"))  # case-insensitive


def test_validate_audio_rejects_none():
    with pytest.raises(ValidationError):
        validate_audio_upload(None)


def test_validate_audio_rejects_empty_filename():
    with pytest.raises(ValidationError):
        validate_audio_upload(_fs(""))


def test_validate_audio_rejects_other_extension():
    with pytest.raises(ValidationError, match=".mp3"):
        validate_audio_upload(_fs("song.wav"))


def test_validate_key_accepts_png_jpg_jpeg():
    for name in ("key.png", "K.PNG", "key.jpg", "key.JPEG"):
        validate_key_upload(_fs(name))


def test_validate_key_rejects_none():
    with pytest.raises(ValidationError):
        validate_key_upload(None)


def test_validate_key_rejects_bad_extension():
    with pytest.raises(ValidationError):
        validate_key_upload(_fs("file.gif"))
