"""Command-line interface for the audio signature system."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import click

from core.decoder import decode_graphic_key, verify_against_mp3
from core.fingerprint import generate_fingerprint
from core.graphic_key import build_graphic_key
from core.metadata import read_metadata, resolve_title, write_signature_tag


@click.group()
def cli():
    """Audio Signature — fingerprint MP3s into scannable graphic keys."""


@cli.command()
@click.argument("mp3_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    "-o",
    default="./keys/",
    help="Output directory for the graphic key PNG.",
)
def encode(mp3_path: str, output: str):
    """Fingerprint MP3_PATH, tag it, and write a graphic key PNG."""
    os.makedirs(output, exist_ok=True)

    fingerprint_data = generate_fingerprint(mp3_path)
    meta = read_metadata(mp3_path)
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

    base = os.path.splitext(os.path.basename(mp3_path))[0]
    out_png = os.path.join(output, f"{base}_key.png")

    meta_for_key = dict(meta)
    meta_for_key["timestamp"] = timestamp
    build_graphic_key(mp3_path, out_png, meta_for_key, fingerprint_data)

    click.echo(f"Fingerprint hash: {fingerprint_data['fingerprint_hash']}")
    click.echo(f"Duration:         {fingerprint_data['duration']}s")
    click.echo(f"Signature tag written to: {mp3_path}")
    click.echo(f"Graphic key saved to:     {out_png}")


@cli.command()
@click.argument("png_path", type=click.Path(exists=True, dir_okay=False))
def decode(png_path: str):
    """Decode a graphic key PNG and print its payload."""
    result = decode_graphic_key(png_path)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.argument("mp3_path", type=click.Path(exists=True, dir_okay=False))
@click.argument("png_path", type=click.Path(exists=True, dir_okay=False))
def verify(mp3_path: str, png_path: str):
    """Verify MP3_PATH against its graphic key PNG_PATH."""
    result = verify_against_mp3(png_path, mp3_path)
    click.echo(json.dumps(result, indent=2))
    raise SystemExit(0 if result["match"] else 1)


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host.")
@click.option("--port", default=5000, type=int, help="Bind port.")
@click.option("--debug", is_flag=True, help="Run Flask in debug mode.")
def serve(host: str, port: int, debug: bool):
    """Start the Flask API server."""
    from app import create_app

    create_app().run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    cli()
