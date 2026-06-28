"""Command-line interface for the audio signature system."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import click

from core.fingerprint import generate_fingerprint
from core.metadata import read_metadata, resolve_title, write_signature_tag
from core.pixel_glyph import (
    decode_glyph,
    generate_glyph,
    list_luts,
    render_glyph_display,
    verify_glyph_against_mp3,
)


@click.group()
def cli():
    """Audio Signature — fingerprint MP3s into self-contained pixel glyphs."""


@cli.command()
@click.argument("mp3_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    "-o",
    default="./keys/",
    help="Output directory for the glyph PNG.",
)
@click.option(
    "--lut",
    default="magma",
    type=click.Choice(list_luts()),
    help="Pixel glyph colour LUT.",
)
@click.option(
    "--size",
    type=click.Choice(["64", "256"]),
    default="64",
    show_default=True,
    help="Glyph output size. 256px is display-only (not decodable).",
)
def encode(mp3_path: str, output: str, lut: str, size: str):
    """Fingerprint MP3_PATH, tag it, and write a pixel glyph PNG."""
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
    glyph_png = os.path.join(output, f"{base}_glyph.png")

    glyph_info = generate_glyph(mp3_path, glyph_png, lut_name=lut)

    click.echo(f"Fingerprint hash: {fingerprint_data['fingerprint_hash']}")
    click.echo(f"Duration:         {fingerprint_data['duration']}s")
    click.echo(f"LUT:              {lut}")
    click.echo(f"Signature tag written to: {mp3_path}")
    click.echo(f"Pixel glyph saved to:   {glyph_info['glyph_path']}")
    if "display_path" in glyph_info:
        click.echo(f"Glyph display (256px):  {glyph_info['display_path']}")

    if size == "256":
        native_path = os.path.join(output, f"{base}_glyph_256native.png")
        display_img = render_glyph_display(
            mp3_path, lut_name=lut, fingerprint_data=fingerprint_data
        )
        display_img.save(native_path, format="PNG", optimize=False)
        click.echo(f"Native 256px glyph:    {native_path}")
        click.echo("Note: 256px glyph is display-only and cannot be decoded.")


@cli.command("decode-glyph")
@click.argument("png_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--size",
    type=click.Choice(["64", "256"]),
    default="64",
    show_default=True,
    help="Glyph size. Only 64px is decodable.",
)
def decode_glyph_cmd(png_path: str, size: str):
    """Decode a 64×64 pixel glyph PNG and print its payload."""
    if size == "256":
        click.echo(
            "Error: 256px glyphs are display-only. Decode requires the 64px glyph.",
            err=True,
        )
        raise SystemExit(1)
    result = decode_glyph(png_path)
    result.pop("fingerprint_bytes", None)
    click.echo(json.dumps(result, indent=2))


@cli.command("verify-glyph")
@click.argument("png_path", type=click.Path(exists=True, dir_okay=False))
@click.argument("mp3_path", type=click.Path(exists=True, dir_okay=False))
def verify_glyph_cmd(png_path: str, mp3_path: str):
    """Verify a pixel glyph PNG against MP3_PATH."""
    result = verify_glyph_against_mp3(png_path, mp3_path)
    serializable = dict(result)
    decoded = dict(serializable.get("decoded") or {})
    decoded.pop("fingerprint_bytes", None)
    serializable["decoded"] = decoded
    click.echo(json.dumps(serializable, indent=2))
    raise SystemExit(0 if result["match"] else 1)


@cli.command()
def luts():
    """List available pixel glyph colour LUTs."""
    click.echo("Available LUTs:")
    for name in list_luts():
        click.echo(f"  - {name}")


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
