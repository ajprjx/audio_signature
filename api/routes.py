"""Flask blueprint exposing /api/encode, /api/decode and /api/verify."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from core.decoder import decode_graphic_key, verify_against_mp3
from core.fingerprint import FingerprintError, generate_fingerprint
from core.graphic_key import build_graphic_key
from core.metadata import read_metadata, write_signature_tag

from .schemas import ValidationError, validate_audio_upload, validate_key_upload

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _save_temp(file_storage, suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    file_storage.save(tmp.name)
    tmp.close()
    return tmp.name


def _cleanup(*paths: str) -> None:
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@api_bp.route("/encode", methods=["POST"])
def encode():
    """Fingerprint an uploaded MP3 and return a base64 PNG graphic key."""
    mp3_path = None
    png_path = None
    try:
        file = request.files.get("file")
        validate_audio_upload(file)

        mp3_path = _save_temp(file, ".mp3")
        png_fd, png_path = tempfile.mkstemp(suffix=".png")
        os.close(png_fd)

        fingerprint_data = generate_fingerprint(mp3_path)
        meta = read_metadata(mp3_path)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        signature_payload = {
            "fingerprint_hash": fingerprint_data["fingerprint_hash"],
            "duration": fingerprint_data["duration"],
            "title": meta.get("title", "Unknown Title"),
            "artist": meta.get("artist", "Unknown Artist"),
            "timestamp": timestamp,
        }
        write_signature_tag(mp3_path, signature_payload)

        meta_for_key = dict(meta)
        meta_for_key["timestamp"] = timestamp
        build_graphic_key(mp3_path, png_path, meta_for_key, fingerprint_data)

        with open(png_path, "rb") as fh:
            png_b64 = base64.b64encode(fh.read()).decode("ascii")

        return jsonify(
            {
                "graphic_key": png_b64,
                "metadata": {
                    "title": signature_payload["title"],
                    "artist": signature_payload["artist"],
                    "duration": fingerprint_data["duration"],
                    "fingerprint_hash": fingerprint_data["fingerprint_hash"],
                },
            }
        )
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except FingerprintError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Processing error: {exc}"}), 500
    finally:
        _cleanup(mp3_path, png_path)


@api_bp.route("/decode", methods=["POST"])
def decode():
    """Decode an uploaded graphic key PNG into its payload."""
    png_path = None
    try:
        file = request.files.get("file")
        validate_key_upload(file)

        png_path = _save_temp(file, ".png")
        result = decode_graphic_key(png_path)
        return jsonify(result)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Processing error: {exc}"}), 500
    finally:
        _cleanup(png_path)


@api_bp.route("/verify", methods=["POST"])
def verify():
    """Verify an uploaded MP3 against its uploaded graphic key."""
    mp3_path = None
    png_path = None
    try:
        mp3_file = request.files.get("mp3")
        key_file = request.files.get("graphic_key")
        validate_audio_upload(mp3_file)
        validate_key_upload(key_file)

        mp3_path = _save_temp(mp3_file, ".mp3")
        png_path = _save_temp(key_file, ".png")

        result = verify_against_mp3(png_path, mp3_path)
        return jsonify(result)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except FingerprintError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Processing error: {exc}"}), 500
    finally:
        _cleanup(mp3_path, png_path)
