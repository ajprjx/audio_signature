"""Request/response validation helpers for the API."""

from __future__ import annotations

import os

ALLOWED_AUDIO_EXT = {".mp3"}
ALLOWED_KEY_EXT = {".png", ".jpg", ".jpeg"}


class ValidationError(ValueError):
    """Raised when an uploaded file fails validation."""


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def validate_audio_upload(file_storage) -> None:
    """Validate a werkzeug FileStorage holding an MP3 upload."""
    if file_storage is None or not file_storage.filename:
        raise ValidationError("No file provided.")
    if _ext(file_storage.filename) not in ALLOWED_AUDIO_EXT:
        raise ValidationError("Audio file must be a .mp3.")


def validate_key_upload(file_storage) -> None:
    """Validate a werkzeug FileStorage holding a graphic-key image upload."""
    if file_storage is None or not file_storage.filename:
        raise ValidationError("No file provided.")
    if _ext(file_storage.filename) not in ALLOWED_KEY_EXT:
        raise ValidationError("Graphic key must be a .png/.jpg image.")
