# Audio Signature System

An audio fingerprinting and **visual key** system. Given an MP3, it:

1. Generates a unique **chromaprint fingerprint**.
2. Embeds the fingerprint into the MP3's **ID3 metadata** (a custom
   `TXXX:AudioSignature` frame, base64 JSON).
3. Produces a styled **PNG graphic key** — a high-error-correction QR code
   beside a neon waveform visualization.
4. Exposes a **Flask REST API** and a **CLI** for encode / decode / verify.

The graphic key is the core artifact: a visually distinctive PNG that encodes
the fingerprint + metadata, and can be scanned back to recover song identity.

---

## Layout

```
audio_signature/
├── app.py                  # Flask app factory
├── cli.py                  # CLI entry point (click)
├── core/
│   ├── fingerprint.py      # Chromaprint fingerprinting + comparison
│   ├── metadata.py         # ID3 tag read/write via mutagen
│   ├── waveform.py         # Waveform image via librosa + Pillow
│   ├── graphic_key.py      # QR + waveform compositing, QR decode
│   └── decoder.py          # Decode + verify pipelines
├── api/
│   ├── routes.py           # /api/encode, /api/decode, /api/verify
│   └── schemas.py          # Upload validation
├── tests/
│   └── test_roundtrip.py   # Encode → decode → verify roundtrip
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
# Encode: fingerprint, tag the MP3, write a graphic key PNG into ./keys/
python cli.py encode path/to/song.mp3 --output ./keys/

# Decode: read a graphic key PNG back into its payload
python cli.py decode ./keys/song_key.png

# Verify: re-fingerprint the MP3 and compare against its graphic key
python cli.py verify path/to/song.mp3 ./keys/song_key.png

# Serve the REST API
python cli.py serve --host 0.0.0.0 --port 5000
```

---

## REST API

Start it with `python cli.py serve` (or `python app.py`).

### `POST /api/encode`

`multipart/form-data` with field `file` (an MP3).

Response JSON:

```json
{
  "graphic_key": "<base64 PNG>",
  "metadata": {
    "title": "...",
    "artist": "...",
    "duration": 213.4,
    "fingerprint_hash": "abc123..."
  }
}
```

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
┌─────────────────────────────────┐
│            SONG TITLE            │  top label (white, monospace)
│        Artist · Duration         │  sub-label
├──────────────────┬──────────────┤
│                  │              │
│    QR CODE       │   WAVEFORM   │  side by side, vertically centered
│   (left half)    │ (right half) │
│                  │              │
├──────────────────┴──────────────┤
│   fingerprint_hash  [timestamp]  │  footer, small monospace
└─────────────────────────────────┘
```

- Canvas: 600×300, background `#0A0A0A`.
- QR: white modules, ~220×220, `ERROR_CORRECT_H` (30% redundancy).
- Waveform: neon `#00FFAA`, 260×160, kept strictly in the right panel — never
  layered over the QR modules.
- Separator line `#333333` between the two panels.

The QR payload (base64 JSON) carries the full chromaprint string plus
metadata, so the key is self-describing.

---

## Tests

```bash
pytest tests/
```

`test_roundtrip.py` synthesizes a short sine-sweep MP3 (no network needed),
runs the full encode pipeline, reads back the ID3 tag, decodes the PNG, and
verifies the MP3 against its key. It skips gracefully if `fpcalc`, `ffmpeg`,
or a QR backend are unavailable.

---

## Implementation notes

- **`fpcalc` detection:** every fingerprint call checks the binary is on PATH
  and raises a clear `FingerprintError` if not.
- **QR error correction H** keeps decoding robust; the waveform is laid out
  beside the QR rather than over it, so the quiet zone is never disturbed.
- **Fonts:** a bundled-monospace TTF is loaded if found (DejaVu Sans Mono,
  Menlo, Monaco…), otherwise `ImageFont.load_default()`.
- **QR backends:** `pyzbar` is tried first, then `zxing-cpp`.
