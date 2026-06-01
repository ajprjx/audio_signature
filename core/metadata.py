"""ID3 tag read/write via mutagen.

Stores the audio signature payload in a custom ``TXXX:AudioSignature`` frame,
base64-encoded JSON, so it round-trips cleanly through standard ID3 tooling.
"""

from __future__ import annotations

import base64
import json

from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
from mutagen.mp3 import MP3

SIGNATURE_DESC = "AudioSignature"

# Maps human field names to the ID3 frame ids we read them from.
_TEXT_FRAMES = {
    "title": "TIT2",
    "artist": "TPE1",
    "album": "TALB",
    "year": "TDRC",
    "bpm": "TBPM",
}


def read_metadata(mp3_path: str) -> dict:
    """Extract common ID3 tags plus the custom AudioSignature tag if present."""
    result: dict = {}
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = None

    if tags is not None:
        for field, frame_id in _TEXT_FRAMES.items():
            frame = tags.get(frame_id)
            if frame is not None and frame.text:
                result[field] = str(frame.text[0])

    # Always include duration from the audio stream when readable.
    try:
        audio = MP3(mp3_path)
        if audio.info is not None:
            result["duration"] = round(float(audio.info.length), 1)
    except Exception:
        pass

    signature = read_signature_tag(mp3_path)
    if signature is not None:
        result["signature"] = signature

    return result


def write_signature_tag(mp3_path: str, signature_payload: dict) -> None:
    """Write the AudioSignature TXXX frame as base64(json(payload))."""
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()

    encoded = base64.b64encode(
        json.dumps(signature_payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    # Remove any existing AudioSignature frame before adding the new one.
    tags.delall(f"TXXX:{SIGNATURE_DESC}")
    tags.add(TXXX(encoding=3, desc=SIGNATURE_DESC, text=[encoded]))
    tags.save(mp3_path)


def read_signature_tag(mp3_path: str) -> dict | None:
    """Read and decode the TXXX:AudioSignature tag, or None if absent."""
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        return None

    frame = tags.get(f"TXXX:{SIGNATURE_DESC}")
    if frame is None or not frame.text:
        return None

    try:
        raw = base64.b64decode(frame.text[0])
        return json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
