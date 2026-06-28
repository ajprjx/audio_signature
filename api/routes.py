"""Flask blueprint exposing /api/encode, /api/decode/glyph and /api/verify/glyph."""

from __future__ import annotations

import base64
import os
import tempfile
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from io import BytesIO

from PIL import Image

from core.fingerprint import FingerprintError, generate_fingerprint
from core.metadata import read_metadata, resolve_title, write_signature_tag
from core.pixel_glyph import (
    decode_glyph,
    list_luts,
    render_glyph_display,
    render_glyph_image,
    verify_glyph_against_mp3,
)

from .schemas import (
    ValidationError,
    validate_audio_upload,
    validate_glyph_size,
    validate_key_upload,
)

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
    """Fingerprint an uploaded MP3 and return a base64 PNG pixel glyph."""
    mp3_path = None
    try:
        file = request.files.get("file")
        validate_audio_upload(file)

        mp3_path = _save_temp(file, ".mp3")

        fingerprint_data = generate_fingerprint(mp3_path)
        meta = read_metadata(mp3_path)
        # The upload is saved to a random temp path, so resolve the title from
        # the original upload filename when ID3 tags lack one.
        meta["original_filename"] = file.filename
        meta["title"] = resolve_title(meta, mp3_path)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        signature_payload = {
            "fingerprint_hash": fingerprint_data["fingerprint_hash"],
            "duration": fingerprint_data["duration"],
            "title": meta["title"],
            "artist": meta.get("artist", "Unknown Artist"),
            "timestamp": timestamp,
        }
        write_signature_tag(mp3_path, signature_payload)

        lut_name = request.form.get("lut", "magma")
        if lut_name not in list_luts():
            return jsonify({"error": f"Unknown LUT {lut_name!r}."}), 400

        glyph_size = validate_glyph_size(request.form.get("size"))

        bpm = 0
        if meta.get("bpm"):
            try:
                bpm = int(float(meta["bpm"]))
            except (TypeError, ValueError):
                bpm = 0

        # The 64×64 glyph is always built — it's the decodable artifact and the
        # source of the upscaled display image. When size=256 the user-facing
        # "glyph" field is swapped for the native 256px display render.
        decodable_glyph = render_glyph_image(
            mp3_path, lut_name, fingerprint_data, bpm=bpm
        )
        display_buf = BytesIO()
        decodable_glyph.resize((256, 256), Image.NEAREST).save(
            display_buf, format="PNG", optimize=False
        )
        glyph_display_b64 = base64.b64encode(display_buf.getvalue()).decode("ascii")

        if glyph_size == 256:
            primary_img = render_glyph_display(
                mp3_path, lut_name, fingerprint_data, bpm=bpm
            )
            glyph_decodable = False
        else:
            primary_img = decodable_glyph
            glyph_decodable = True

        glyph_buf = BytesIO()
        primary_img.save(glyph_buf, format="PNG", optimize=False)
        glyph_b64 = base64.b64encode(glyph_buf.getvalue()).decode("ascii")

        return jsonify(
            {
                "glyph": glyph_b64,
                "glyph_display": glyph_display_b64,
                "glyph_size": glyph_size,
                "glyph_decodable": glyph_decodable,
                "metadata": {
                    "title": signature_payload["title"],
                    "artist": signature_payload["artist"],
                    "duration": fingerprint_data["duration"],
                    "fingerprint_hash": fingerprint_data["fingerprint_hash"],
                    "lut_name": lut_name,
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
        _cleanup(mp3_path)


@api_bp.route("/decode/glyph", methods=["POST"])
def decode_glyph_route():
    """Decode an uploaded 64×64 pixel glyph PNG.

    The optional ``size`` form field defaults to ``"64"``. Passing ``"256"``
    yields a 400 response because 256px glyphs are display-only and carry no
    Reed–Solomon payload.
    """
    png_path = None
    try:
        file = request.files.get("file")
        validate_key_upload(file)

        glyph_size = validate_glyph_size(request.form.get("size"))
        if glyph_size == 256:
            return (
                jsonify(
                    {"error": "256px glyphs are display-only and cannot be decoded."}
                ),
                400,
            )

        png_path = _save_temp(file, ".png")
        result = decode_glyph(png_path)
        payload = dict(result)
        payload.pop("fingerprint_bytes", None)
        return jsonify(payload)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Processing error: {exc}"}), 500
    finally:
        _cleanup(png_path)


@api_bp.route("/verify/glyph", methods=["POST"])
def verify_glyph_route():
    """Verify an uploaded MP3 against its uploaded 64×64 pixel glyph.

    Decodes the glyph's Reed–Solomon-protected fingerprint and compares it,
    byte-for-byte plus CRC32, against a freshly computed fingerprint of the MP3.
    """
    mp3_path = None
    png_path = None
    try:
        mp3_file = request.files.get("mp3")
        glyph_file = request.files.get("glyph")
        validate_audio_upload(mp3_file)
        validate_key_upload(glyph_file)

        mp3_path = _save_temp(mp3_file, ".mp3")
        png_path = _save_temp(glyph_file, ".png")

        result = verify_glyph_against_mp3(png_path, mp3_path)
        # ``decoded`` carries raw fingerprint_bytes, which is not JSON-serializable.
        decoded = dict(result.get("decoded", {}))
        decoded.pop("fingerprint_bytes", None)
        result["decoded"] = decoded
        return jsonify(result)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except FingerprintError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Processing error: {exc}"}), 500
    finally:
        _cleanup(mp3_path, png_path)
