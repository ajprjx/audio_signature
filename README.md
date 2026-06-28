# Audio Signature System

An audio fingerprinting and **visual signature** system. Given an MP3, it:

1. Generates a unique **acoustic fingerprint** from the sound itself.
2. Embeds an identity payload in the MP3's **ID3 metadata** (`TXXX:AudioSignature`).
3. Renders a self-contained **64×64 pixel glyph PNG** — Reed–Solomon protected,
   decodable straight from the pixels, no scanner required.
4. Exposes **encode / decode / verify** through a **Flask REST API** and a **CLI**.

The glyph *is* the signature: the acoustic identity is stored directly in the
pixel values and recovered with `decode_glyph()`.

---

## How it works

### The signature (acoustic fingerprint)

The "signature" isn't a cryptographic key — it's an **acoustic identity derived
from the sound itself**.

1. **Listen to the audio.** The `fpcalc` tool (Chromaprint) analyses the first
   60 seconds of the MP3 and produces a *chromaprint* — a compact summary of how
   the music's frequencies change over time. Two recordings of the same track
   produce near-identical chromaprints; different songs produce very different
   ones.
2. **Shrink it to a fixed size.** The chromaprint is packed into exactly
   **120 bytes** so it always fits the same space, plus a short **16-character
   hash** (truncated SHA-256) for a human-readable ID.
3. **Store it.** The hash and basic metadata (title, artist, duration) are
   written into the MP3's own **ID3 tag** (`TXXX:AudioSignature`); the full
   fingerprint travels inside the glyph image.

To **verify** a track later, we re-fingerprint it the same way and compare. The
glyph requires an exact 120-byte match (with Reed–Solomon repair tolerating
some pixel damage first).

### The image (pixel glyph)

The **64×64 PNG glyph** is a self-contained image that *is* the data:

1. The 120-byte fingerprint gets **Reed–Solomon error-correction** added (so the
   image survives some damage), alongside a 128-point loudness waveform.
2. These bytes are laid out along a **clockwise inward spiral** of pixels, each
   byte stored in a pixel's **red channel**.
3. The bytes run through a colour **palette (LUT)** — `magma`, `viridis`,
   `inferno`, `plasma`, or `copper` — so the result looks like art instead of
   noise. A tiny **manifest** in the bottom-right 4×4 corner records the palette,
   length, duration, and a checksum so a decoder can read everything back.
4. A decorative **Julia-set fractal** (warped by the waveform) is blended into
   the green and blue channels *only* — pure decoration that never touches the
   red data channel, so the glyph stays perfectly decodable.

Because the data lives in the pixels, anyone with `decode_glyph()` recovers the
fingerprint with no QR scanner and no sidecar file. A 256×256 upscale is also
produced for display, but only the 64×64 original is decodable.

---

## Layout

```
audio_signature/
├── app.py                  # Flask app factory (serves UI + API)
├── cli.py                  # CLI entry point (click)
├── static/
│   └── index.html          # Glyph-only web UI (generate / decode / verify)
├── core/
│   ├── fingerprint.py      # Chromaprint fingerprinting + comparison
│   ├── metadata.py         # ID3 tag read/write via mutagen
│   ├── waveform.py         # RMS loudness envelope + image
│   └── pixel_glyph.py      # 64×64 glyph encode/decode (spiral + RS + LUT)
├── api/
│   ├── routes.py           # /api/encode, /api/decode/glyph, /api/verify/glyph
│   └── schemas.py          # Upload validation
├── tests/
│   ├── conftest.py         # Shared sample_mp3 fixture
│   └── test_pixel_glyph.py # Glyph roundtrip + LUT tests
└── requirements.txt
```

---

## Setup

### System dependencies

The chromaprint `fpcalc` binary must be on your `PATH`.

**Debian / Ubuntu**

```bash
apt-get install -y ffmpeg libchromaprint-tools
```

**macOS (Homebrew)**

```bash
brew install ffmpeg chromaprint
```

`fpcalc` comes from `libchromaprint-tools` / `chromaprint`. `ffmpeg` is only
needed to synthesize the test MP3.

### Python dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## CLI usage

```bash
# Encode: fingerprint, tag the MP3, write the pixel glyph into ./keys/
python cli.py encode path/to/song.mp3 --output ./keys/ --lut magma

# Decode a 64×64 pixel glyph
python cli.py decode-glyph ./keys/song_glyph.png

# Verify an MP3 against its glyph
python cli.py verify-glyph ./keys/song_glyph.png path/to/song.mp3

# List available glyph colour palettes (LUTs)
python cli.py luts

# Serve the web UI + REST API
python cli.py serve --host 0.0.0.0 --port 5000
```

---

## Web UI

Start the server and open <http://localhost:5000/>. A single self-contained page
(`static/index.html`) provides three actions, all against the glyph:

- **Generate** — pick an MP3, generate and preview the glyph, download the PNG.
- **Decode** — drop a glyph PNG and see the decoded fingerprint + metadata.
- **Verify** — pick an MP3 + its glyph and see the match result.

It's vanilla HTML/JS calling the endpoints below — no build step.

---

## REST API

Start it with `python cli.py serve` (or `python app.py`).

### `POST /api/encode`

`multipart/form-data` with field `file` (an MP3). Optional `lut` —
`magma` | `viridis` | `inferno` | `plasma` | `copper`.

Response JSON:

```json
{
  "glyph": "<base64 64×64 PNG>",
  "glyph_display": "<base64 256×256 PNG>",
  "metadata": {
    "title": "...",
    "artist": "...",
    "duration": 213.4,
    "fingerprint_hash": "abc123...",
    "lut_name": "magma"
  }
}
```

### `POST /api/decode/glyph`

`multipart/form-data` with field `file` (a 64×64 glyph PNG).

```json
{
  "fingerprint_hex": "...",
  "duration": 213.4,
  "bpm": 0,
  "lut_name": "magma",
  "verified": true,
  "crc_match": true,
  "ecc_corrections": 0
}
```

### `POST /api/verify/glyph`

`multipart/form-data` with fields `mp3` and `glyph` (a PNG).

```json
{
  "match": true,
  "bytes_match": true,
  "crc_match": true,
  "decoded": { "...": "..." },
  "live": { "...": "..." }
}
```

### `GET /health`

```json
{ "status": "ok" }
```

Errors return `{"error": "message"}` with a 400 (bad input), 413 (too large),
or 500 (processing error) status. Temp files are always cleaned up in `finally`
blocks.

---

## Pixel glyph (64×64)

A standalone PNG encoding the 120-byte fingerprint via a clockwise spiral,
RS(255,120) error correction, and a perceptual colour LUT, with a 4×4
micro-manifest in the bottom-right corner. **PNG only** — JPEG recompression
destroys the pixel data. See `core/pixel_glyph.py` and `CLAUDE.md` for the full
byte layout.

---

## Tests

```bash
pytest tests/
```

`test_pixel_glyph.py` covers glyph roundtrip, all five LUTs, JPEG rejection, and
LUT monotonicity. Tests synthesize a 10-second sine-sweep MP3 (no network) and
skip gracefully if `fpcalc` or `ffmpeg` are unavailable.

---

## Implementation notes

- **`fpcalc` detection:** every fingerprint call checks the binary is on PATH
  and raises a clear `FingerprintError` if not.
- **Bounded fingerprint window:** chromaprint length scales with audio duration,
  so `generate_fingerprint` analyses a leading window (`DEFAULT_MAX_SECONDS`,
  60 s) for a compact, stable identity. Encode and verify use the same window,
  so matching stays exact. The reported `duration` is still the full song
  length. Pass `max_seconds=0` to fingerprint the whole file.
- **Data in the red channel:** each spiral pixel's red channel carries one data
  byte through an invertible LUT; the Julia-set visual layer only modulates
  green/blue, so decoding is unaffected.
- **Error correction:** RS(255,120) via `reedsolo>=1.7.0` repairs damaged
  pixels; a CRC32 in the manifest is reported separately as an advisory check.
- **PNG only:** the glyph is saved and decoded as PNG; JPEG is rejected at both
  ends.
</content>
</invoke>
