"""Click CLI smoke tests."""

from __future__ import annotations

import json
import os
import shutil

from click.testing import CliRunner

from cli import cli


def test_luts_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["luts"])
    assert result.exit_code == 0
    assert "magma" in result.output
    assert "viridis" in result.output


def test_encode_decode_verify_pipeline(tmp_path, sample_mp3, require_fpcalc, require_qr_backend):
    out_dir = tmp_path / "keys"
    runner = CliRunner()

    # Encode.
    result = runner.invoke(cli, ["encode", sample_mp3, "-o", str(out_dir), "--lut", "viridis"])
    assert result.exit_code == 0, result.output
    base = os.path.splitext(os.path.basename(sample_mp3))[0]
    key_png = out_dir / f"{base}_key.png"
    glyph_png = out_dir / f"{base}_glyph.png"
    assert key_png.exists()
    assert glyph_png.exists()
    assert "Fingerprint hash:" in result.output

    # Decode graphic key.
    result = runner.invoke(cli, ["decode", str(key_png)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verified"] is True
    assert payload["fingerprint_hash"]

    # Decode glyph.
    result = runner.invoke(cli, ["decode-glyph", str(glyph_png)])
    assert result.exit_code == 0, result.output
    glyph_payload = json.loads(result.output)
    assert glyph_payload["verified"] is True

    # Verify graphic key against MP3 (exit 0 on match).
    result = runner.invoke(cli, ["verify", sample_mp3, str(key_png)])
    assert result.exit_code == 0, result.output
    verify_payload = json.loads(result.output)
    assert verify_payload["match"] is True

    # Verify glyph against MP3.
    result = runner.invoke(cli, ["verify-glyph", str(glyph_png), sample_mp3])
    assert result.exit_code == 0, result.output


def test_verify_exit_1_on_mismatch(
    tmp_path, sample_mp3, sample_mp3_alt, require_fpcalc, require_qr_backend
):
    out_dir = tmp_path / "keys"
    runner = CliRunner()
    runner.invoke(cli, ["encode", sample_mp3, "-o", str(out_dir)])

    base = os.path.splitext(os.path.basename(sample_mp3))[0]
    key_png = out_dir / f"{base}_key.png"

    # Verify against a different MP3 — should mismatch and exit 1.
    result = runner.invoke(cli, ["verify", sample_mp3_alt, str(key_png)])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["match"] is False
