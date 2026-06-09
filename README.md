# Audio Signature System

An audio fingerprinting and **visual key** system. Given an MP3, it:

1. Generates a unique **chromaprint fingerprint**.
2. Embeds the fingerprint into the MP3's **ID3 metadata** (a custom
   `TXXX:AudioSignature` frame, base64 JSON).
3. Produces a styled **800×300 PNG graphic key** — QR code, neon waveform, and
   a **64×64 pixel glyph** panel.
4. Writes a standalone **64×64 pixel glyph PNG** — Reed–Solomon protected,
   self-contained, no QR scanner required.
5. Exposes a **Flask REST API** and a **CLI** for encode / decode / verify.

The graphic key is scannable via QR; the pixel glyph encodes the same acoustic
identity directly in pixel values and decodes with `decode_glyph()`.

---

## Layout

```
audio_signature/
├── app.py                  # Flask app factory (serves UI + API)
├── cli.py                  # CLI entry point (click)
├── static/
│   └── index.html          # Minimal web UI (encode / decode / verify)
├── core/
│   ├── fingerprint.py      # Chromaprint fingerprinting + comparison
│   ├── metadata.py         # ID3 tag read/write via mutagen
│   ├── waveform.py         # Waveform image via librosa + Pillow
│   ├── pixel_glyph.py      # 64×64 glyph encode/decode (spiral + RS + LUT)
│   ├── graphic_key.py      # QR + waveform + glyph compositing, QR decode
│   └── decoder.py          # Graphic key decode + verify pipelines
├── api/
│   ├── routes.py           # /api/encode, /api/decode, /api/decode/glyph, /api/verify
│   └── schemas.py          # Upload validation
├── tests/
│   ├── conftest.py         # Shared sample_mp3 fixture
│   ├── test_roundtrip.py   # Graphic key QR roundtrip
│   └── test_pixel_glyph.py # Pixel glyph roundtrip + LUT tests
└── requirements.txt
```

---

## Setup

### System dependencies

The chromaprint `fpcalc` binary must be on your `PATH`, and you need a QR
decoder backend.

**Debian / Ubuntu**

```bash
apt-get install -y ffmpeg libchromaprint-tools libzbar0
```

**macOS (Homebrew)**

```bash
brew install ffmpeg chromaprint zbar
```

- `fpcalc` comes from `libchromaprint-tools` / `chromaprint`.
- `libzbar0` / `zbar` is required by `pyzbar`. If you can't install it, the
  code falls back to the pure-python `zxing-cpp` wheel automatically.

### Python dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

## CLI usage

```bash
# Encode: fingerprint, tag the MP3, write graphic key + pixel glyph into ./keys/
python cli.py encode path/to/song.mp3 --output ./keys/ --lut magma

# Decode a graphic key (QR payload)
python cli.py decode ./keys/song_key.png

# Decode a standalone 64×64 pixel glyph
python cli.py decode-glyph ./keys/song_glyph.png

# Verify MP3 against graphic key or pixel glyph
python cli.py verify path/to/song.mp3 ./keys/song_key.png
python cli.py verify-glyph ./keys/song_glyph.png path/to/song.mp3

# List available glyph colour LUTs
python cli.py luts

# Serve the REST API
python cli.py serve --host 0.0.0.0 --port 5000
```

---

## Web UI

Start the server and open <http://localhost:5000/> in a browser. A single
self-contained page (`static/index.html`) provides three tabs:

- **Encode** — pick an MP3, generate and preview the graphic key, download the PNG.
- **Decode** — drop a graphic-key image and see the decoded payload.
- **Verify** — pick an MP3 + its key and see the match result.

It's vanilla HTML/JS calling the same endpoints below — no build step.

## REST API

Start it with `python cli.py serve` (or `python app.py`).

### `POST /api/encode`

`multipart/form-data` with field `file` (an MP3).

Response JSON:

```json
{
  "graphic_key": "<base64 PNG>",
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

Optional form field `lut` — one of `magma`, `viridis`, `inferno`, `plasma`, `copper`.

### `POST /api/decode`

`multipart/form-data` with field `file` (a PNG/JPG graphic key).

Response JSON:

```json
{
  "title": "...",
  "artist": "...",
  "duration": 213.4,
  "fingerprint_hash": "abc123",
  "fingerprint": "...",
  "generated_at": "2024-01-15T10:30:00Z",
  "verified": true
}
```

### `POST /api/decode/glyph`

`multipart/form-data` with field `file` (a 64×64 glyph PNG).

Response JSON:

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

### `POST /api/verify`

`multipart/form-data` with fields `mp3` and `graphic_key`.

Response JSON:

```json
{
  "match": true,
  "similarity": 0.97,
  "key_metadata": { "...": "..." },
  "mp3_metadata": { "...": "..." }
}
```

Errors return `{"error": "message"}` with a 400 (bad input) or 500
(processing error) status. Temp files are always cleaned up in `finally`
blocks.

---

## Graphic key layout

```
┌──────────────────────────────────────────────────────────────┐
│                        SONG TITLE                             │
│                    Artist · Duration                          │
├─────────────────┬─────────────────┬──────────────────────────┤
│    QR CODE      │    WAVEFORM     │   PIXEL GLYPH (128×128)  │
│   (220×220)     │   (252×160)     │   NEAREST upscale of 64² │
├─────────────────┴─────────────────┴──────────────────────────┤
│              fingerprint_hash  [timestamp]                      │
└──────────────────────────────────────────────────────────────┘
```

- Canvas: **800×300**, background `#0A0A0A`.
- Three equal panels separated by `#333333` lines.
- QR: white modules, ~220×220, adaptive error correction.
- Waveform: neon `#00FFAA`, centred in the middle panel.
- Glyph: 64×64 pixel art upscaled 2× with `Image.NEAREST` in the right panel.

## Pixel glyph (64×64)

Standalone PNG encoding fingerprint bytes via a clockwise spiral, RS(255,120)
error correction, and a perceptual colour LUT. See `core/pixel_glyph.py` and
`claude.md` for the full byte layout. **PNG only** — never JPEG.

The QR payload (base64 JSON) carries the full chromaprint string plus
metadata, so the key is self-describing.

---

## Tests

```bash
pytest tests/
```

`test_roundtrip.py` exercises the QR graphic key pipeline; `test_pixel_glyph.py`
covers glyph roundtrip, all five LUTs, JPEG rejection, and LUT monotonicity.
Tests synthesize a 10-second sine-sweep MP3 (no network). They skip gracefully
if `fpcalc`, `ffmpeg`, or a QR backend are unavailable.

---

## Implementation notes

- **`fpcalc` detection:** every fingerprint call checks the binary is on PATH
  and raises a clear `FingerprintError` if not.
- **Bounded fingerprint window:** chromaprint fingerprint length scales with
  audio duration, and a full song's fingerprint exceeds the maximum QR capacity
  (version 40 ≈ 2953 bytes at the lowest error correction). `generate_fingerprint`
  therefore analyses a leading window (`DEFAULT_MAX_SECONDS`, 60 s) so the
  payload fits. Both encode and verify use the same window, so matching stays
  exact. The reported `duration` is still the full song length. Pass
  `max_seconds=0` to fingerprint the whole file.
- **Adaptive QR encoding:** the payload is zlib-compressed (marked with a `Z1:`
  prefix; the decoder also still reads legacy plain-base64 keys). The builder
  picks the highest error-correction level that fits (H → Q → M → L). If even
  the full fingerprint won't fit at level L, it falls back to a compact payload
  that keeps the fingerprint *hash* and metadata but drops the full fingerprint
  string (flagged `fp_truncated`), so encoding never crashes.
- **QR placement:** the waveform is laid out beside the QR rather than over it,
  so the quiet zone is never disturbed (high error correction isn't required).
- **Fonts:** a bundled-monospace TTF is loaded if found (DejaVu Sans Mono,
  Menlo, Monaco…), otherwise `ImageFont.load_default()`.
- **QR backends:** `pyzbar` is tried first, then `zxing-cpp`.
- **Pixel glyph:** 120-byte `fingerprint_bytes` packed from chromaprint frames;
  RS(255,120) via `reedsolo>=1.7.0`; five monotonic LUTs; manifest in
  bottom-right 4×4 block excluded from spiral traversal.
