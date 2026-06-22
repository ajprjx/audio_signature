# Audio Signature — Project Brief

> Agent context document. Last updated: 2026-06-08.
> Primary reference for AI agents working in this repo.

## What this project does

An **audio fingerprinting + visual key** system for MP3 files. Given a track, it:

1. Computes a **Chromaprint** acoustic fingerprint via `fpcalc` (libchromaprint).
2. Embeds a compact identity payload in the MP3's **ID3** metadata (`TXXX:AudioSignature`).
3. Renders a styled **800×300 PNG graphic key** — QR code + waveform + **64×64 pixel glyph** panel.
4. Writes a standalone **64×64 pixel glyph PNG** — Reed–Solomon protected, self-contained, no QR scanner.
5. Exposes **encode / decode / verify** through Flask REST API, Click CLI, and vanilla web UI.

Two parallel identity artifacts:

| Artifact | Size | Encoding | Decode backend |
|---|---|---|---|
| Graphic key | 800×300 PNG | QR (zlib JSON) + visual panels | pyzbar / zxing-cpp |
| Pixel glyph | 64×64 PNG | Spiral pixels + RS(255,120) + LUT | `core/pixel_glyph.py` only |

**Not cryptographic signing.** No keys, HMAC, or asymmetric signatures. "Signature" means acoustic identity derived from audio content, plus a truncated SHA-256 hash for compact display.

---

## Repository layout

```
audio_signature/
├── app.py                  # Flask app factory (UI + API + /health)
├── cli.py                  # Click CLI (encode, decode, decode-glyph, verify, verify-glyph, luts, serve)
├── claude.md               # This file
├── README.md               # User-facing docs
├── requirements.txt
├── static/index.html       # Web UI (glyph-only: Generate / Decode / Verify — Obsidian/Newsreader)
├── docs/signed-glyph/      # Signed-glyph initiative design notes (capacity-research.md)
├── core/
│   ├── fingerprint.py      # Chromaprint + fingerprint_bytes (120B fixed)
│   ├── metadata.py         # ID3 read/write (mutagen)
│   ├── waveform.py         # RMS envelope + bar-chart image
│   ├── pixel_glyph.py      # 64×64 glyph encode/decode
│   ├── graphic_key.py      # QR + waveform + glyph compositing
│   ├── decoder.py          # Graphic key decode + verify
│   ├── spectral.py         # SpectralCodec: lossless bytes↔smooth 256² DCT field (signed-glyph WIP)
│   └── glyph.py            # Ultra-smooth cohesive 256² glyph layer (signed-glyph WIP)
├── api/
│   ├── routes.py           # /api/encode, /decode, /decode/glyph, /verify, /verify/glyph
│   └── schemas.py          # Upload validation (.mp3, .png/.jpg/.jpeg)
└── tests/
    ├── conftest.py         # Shared sample_mp3 fixture (10s sweep)
    ├── test_roundtrip.py   # Graphic key QR roundtrip
    ├── test_pixel_glyph.py # Glyph encode/decode/LUT tests
    ├── test_api.py         # Flask API endpoint tests
    ├── test_spectral.py    # Spectral codec (Feature 1)
    └── test_glyph.py       # Ultra-smooth glyph layer (Feature 2)
```

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
python cli.py serve   # http://localhost:5000
```

**System deps (macOS):** `brew install ffmpeg chromaprint zbar`
**System deps (Debian):** `apt-get install -y ffmpeg libchromaprint-tools libzbar0`

Python 3.13 tested. `audioread` emits deprecation warnings on 3.13 (aifc/sunau shims).

---

## Data flows

### Encode (full pipeline)

```
MP3
  → generate_fingerprint()        # chromaprint string + fingerprint_bytes (120B) + hash
  → read_metadata()               # ID3 tags + duration + optional BPM
  → write_signature_tag()         # TXXX:AudioSignature (hash + metadata only)
  → build_graphic_key()           # 800×300 PNG (QR + waveform + glyph panel)
  → generate_glyph()              # standalone 64×64 + 256×256 display PNG [CLI]
  → render_glyph_image()          # in-memory glyph [API / graphic_key panel]
```

CLI `encode` writes `{base}_key.png` and `{base}_glyph.png`. API `/api/encode` returns
base64 `graphic_key`, `glyph`, and `glyph_display` but does **not** return the tagged MP3.

### Graphic key decode

```
PNG/JPG → QR scan (pyzbar → zxing-cpp) → zlib or legacy base64 JSON
```

### Pixel glyph decode

```
64×64 PNG
  → read micro-manifest (bottom-right 4×4, raw RGB bytes)
  → read spiral pixels → invert LUT → extract RS codeword
  → RS decode → 120-byte fingerprint + CRC32 verify
```

### Verify

| Function | Module | Compares |
|---|---|---|
| `verify_against_mp3` | `decoder.py` | Chromaprint string similarity (Hamming ≥ 0.85) or hash fallback |
| `verify_glyph_against_mp3` | `pixel_glyph.py` | Exact 120-byte `fingerprint_bytes` + CRC32 |

---

## Payload formats

### QR payload (graphic key) — version 1

JSON, zlib-compressed, base64-encoded, prefixed with `Z1:`:

```json
{
  "v": 1,
  "title": "...",
  "artist": "...",
  "duration": 213.4,
  "fp_hash": "abc123...",
  "fingerprint": "<full chromaprint string>",
  "ts": "2024-01-15T10:30:00Z"
}
```

Legacy keys without `Z1:` prefix use plain base64 JSON (still supported).

If the full fingerprint exceeds QR capacity even at error-correction level L, encoding
falls back to a **compact payload**: `fingerprint` cleared, `fp_truncated: true` set.
Verify then compares `fp_hash` only.

### ID3 tag (`TXXX:AudioSignature`)

Base64 JSON — **does not include the full fingerprint**:

```json
{
  "fingerprint_hash": "abc123...",
  "duration": 213.4,
  "title": "...",
  "artist": "...",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Fingerprint hash

`SHA-256(chromaprint_string)[:16]` — 16 hex chars (64 bits). Used for footer display
and compact identity, not for collision-resistant security.

### fingerprint_bytes (glyph)

120-byte fixed-width binary packed from decoded chromaprint uint32 frames (big-endian),
truncated or zero-padded. Hash-chain fallback when libchromaprint ctypes unavailable.
Returned by `generate_fingerprint()` as `fingerprint_bytes`.

---

## Pixel glyph specification (v1)

### Image layout — 64×64

```
┌─────────────────────────────────────────┐
│  spiral region (4080 pixels)            │
│  clockwise inward, manifest excluded    │
│                          ┌── manifest ─┐│
│                          │ 4×4 = 16px ││
│                          └────────────┘│
└─────────────────────────────────────────┘
  Manifest: rows 60–63, cols 60–63 (raw bytes, no LUT)
  Pixel access: pixels[col, row]
```

Spiral: outside-in clockwise over full 64×64 grid, then remove all 16 manifest coords.
Asserted at module load: 4080 spiral + 16 manifest = 4096.

### Micro-manifest (48 bytes = 16 pixels × RGB)

| Bytes | Field |
|---|---|
| 0 | version (`0x01`) |
| 1 | `lut_id` (0–4) |
| 2 | `ecc_level` (`0`=none, `1`=RS(255,120), `2`=RS(255,60); default `1`) |
| 3–4 | fingerprint length uint16 BE (`120`) |
| 5–8 | duration float32 BE |
| 9–10 | BPM uint16 BE (`0` if unknown) |
| 11–14 | CRC32 of fingerprint_bytes BE |
| 15–47 | zero-padded |

### Spiral byte stream (4080 pixels × 3 = 12,240 bytes)

| Pixel range | Content | Bytes |
|---|---|---|
| 0–119 | Fingerprint (triplicated RGB) | 360 |
| 120–239 | RS parity (triplicated) | 360 |
| 240–367 | Waveform 128 values (triplicated) | 384 |
| 368–4079 | SHA-256 hash-chain padding | 11,136 |

Encoding: `RSCodec(120)` → 120 data + 120 parity bytes, each triplicated as `(b,b,b)` per pixel.
Decode extracts via first channel of each triplet pixel (`raw_stream[i*3]`).

### LUTs (strictly monotonic, invertible)

| `lut_id` | Name | Character |
|---|---|---|
| 0 | `magma` | black → purple → orange → cream |
| 1 | `viridis` | purple → teal → green → yellow |
| 2 | `inferno` | black → red → orange → pale yellow |
| 3 | `plasma` | violet → pink → yellow |
| 4 | `copper` | black → brown → copper → gold |

Built from hand-tuned per-channel stops → `np.interp` → `_finalize_monotonic` spread.
Pre-inverted lookup tables built at module load. Assert `np.diff(curve) > 0` per channel.

### `core/pixel_glyph.py` public API

```python
def list_luts() -> list[str]:
    # ["magma", "viridis", "inferno", "plasma", "copper"]

def get_lut_curve(lut_name: str, channel: str) -> np.ndarray:
    # Forward LUT curve for "R", "G", or "B" — used by tests

def render_glyph_image(
    mp3_path: str,
    lut_name: str = "magma",
    fingerprint_data: dict | None = None,
    bpm: int = 0,
) -> Image.Image:
    # In-memory 64×64 glyph; used by graphic_key panel and API

def generate_glyph(
    mp3_path: str,
    output_path: str,
    lut_name: str = "magma",
    also_save_display: bool = True,
) -> dict:
    # Returns: glyph_path, fingerprint_hex, duration, lut_name, crc32
    #          [, display_path if also_save_display]

def decode_glyph(png_path: str) -> dict:
    # Returns: fingerprint_bytes, fingerprint_hex, duration, bpm, lut_name,
    #          verified, crc_match, ecc_corrections, rs_recovered
    # Raises ValueError for non-PNG or wrong dimensions
    # Raises ReedSolomonError if uncorrectable

def verify_glyph_against_mp3(png_path: str, mp3_path: str) -> dict:
    # Returns: match, crc_match, bytes_match, decoded, live
```

PNG only. `also_save_display` uses `Image.NEAREST` upscale to 256×256.

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

Canvas: **800×300** (was 600×300). Three equal `PANEL_W` (~266px) panels.

Key constants in `core/graphic_key.py`:

| Constant | Value |
|---|---|
| `CANVAS_W`, `CANVAS_H` | 800, 300 |
| `PANEL_W` | 266 |
| `QR_SIZE` | 220 |
| `WAVE_W`, `WAVE_H` | 252, 160 |
| `GLYPH_DISPLAY_SIZE` | 128 |
| `HEADER_H`, `FOOTER_H` | 56, 30 |
| `BG_COLOR` | `#0A0A0A` |
| `WAVE_FG` | `#00FFAA` |

`build_graphic_key(..., lut_name="magma")` composites glyph via `render_glyph_image`.

---

## Algorithmic details

### Fingerprinting (`core/fingerprint.py`)

- **Engine:** Chromaprint via `pyacoustid` → shells out to `fpcalc`.
- **Bounded window:** `DEFAULT_MAX_SECONDS = 60`. Full-song fingerprints exceed QR
  version-40 capacity (~2953 bytes at EC-L). Encode and verify share the same window.
  Pass `max_seconds=0` to fingerprint the whole file.
- **Similarity:** Decodes fingerprints to 32-bit frames via `libchromaprint.decode_fingerprint`,
  bitwise Hamming distance. Threshold: **0.85** (hardcoded in `verify_against_mp3`).
- **Homebrew shim:** `_load_chromaprint()` patches `ctypes.CDLL` to find libchromaprint on macOS.

### QR encoding (`core/graphic_key.py`)

- Tries error-correction levels: **H → Q → M → L**.
- Payload zlib-compressed with `Z1:` prefix.
- Falls back to hash-only compact payload if still oversized.

### Waveform (`core/waveform.py`)

- `get_rms_envelope(mp3, n_frames=128)` — list of floats 0.0–1.0 for glyph.
- `generate_waveform_image()` — mirrored RMS bar chart, neon `#00FFAA`, 2× render + LANCZOS downscale.

### Metadata (`core/metadata.py`)

- `resolve_title()` — ID3 title or original upload filename stem.
- `write_signature_tag()` / `read_signature_tag()` — `TXXX:AudioSignature` frame.

---

## API surface

| Endpoint | Method | Fields | Returns |
|---|---|---|---|
| `/api/encode` | POST | `file` (MP3), optional `lut` | `graphic_key`, `glyph`, `glyph_display`, `metadata` (base64 PNGs + JSON) |
| `/api/decode` | POST | `file` (PNG/JPG) | QR payload JSON |
| `/api/decode/glyph` | POST | `file` (PNG) | Decoded glyph JSON (`fingerprint_bytes` stripped) |
| `/api/verify` | POST | `mp3`, `graphic_key` | `{ match, similarity, key_metadata, mp3_metadata }` |
| `/api/verify/glyph` | POST | `mp3`, `glyph` (PNG) | `{ match, bytes_match, crc_match, decoded, live }` (`fingerprint_bytes` stripped from `decoded`) |
| `/health` | GET | — | `{ status: "ok" }` |

- Max upload: **50 MB** (`MAX_CONTENT_LENGTH`).
- Errors: `{ "error": "message" }` with 400 / 413 / 500.
- Temp files cleaned in `finally` blocks.

---

## CLI

```bash
python cli.py encode  song.mp3 -o ./keys/ --lut magma
python cli.py decode  ./keys/song_key.png
python cli.py decode-glyph ./keys/song_glyph.png
python cli.py verify  song.mp3 ./keys/song_key.png        # exit 1 on mismatch
python cli.py verify-glyph ./keys/song_glyph.png song.mp3 # exit 1 on mismatch
python cli.py luts
python cli.py serve --host 0.0.0.0 --port 5000
```

Encode outputs: `{base}_key.png`, `{base}_glyph.png`, `{base}_glyph_256.png`.

---

## Dependencies

### Python (`requirements.txt`)

`pyacoustid`, `librosa`, `soundfile`, `mutagen`, `qrcode[pil]`, `Pillow`, `flask`,
`click`, `numpy`, `scipy`, `reedsolo>=1.7.0`, `pyzbar`/`zxing-cpp`, `pytest`

`colormath` from the original glyph spec is **not** used; LUTs use numpy interpolation.

### System

| Binary | Purpose |
|---|---|
| `fpcalc` | Fingerprinting — **required** |
| `ffmpeg` / `lame` | Test MP3 synthesis |
| `libzbar0` / `zbar` | pyzbar QR decode (optional if zxing-cpp installed) |

---

## Performance (10s synthetic MP3, M-series Mac, 2026-06-08)

| Operation | Latency | Output size |
|---|---|---|
| `generate_glyph` | ~26 ms | ~12 KB PNG |
| `decode_glyph` | ~3 ms | — |
| `build_graphic_key` | ~45 ms | ~31 KB PNG |
| `generate_fingerprint` | dominant (~fpcalc) | 120 B binary |

Glyph encode is I/O-bound on librosa waveform load + fpcalc; decode is PIL/numpy/RS.

---

## Tests

```bash
pytest tests/ -v   # 109 tests
```

| Test file | Coverage |
|---|---|
| `test_roundtrip.py` | QR graphic key encode → ID3 → decode → verify |
| `test_pixel_glyph.py` | Glyph roundtrip, all 5 LUTs, JPEG rejection, LUT monotonicity |
| `test_api.py` | Flask API: encode/decode/decode-glyph/verify/verify-glyph, size modes |
| `test_spectral.py` | Spectral codec: lossless bytes↔field round-trip, capacity, PNG-lossless, smoothness (Feature 1) |
| `test_glyph.py` | Ultra-smooth glyph layer: round-trip, capacity, cohesion transform (Feature 2) |

Shared `sample_mp3` fixture in `tests/conftest.py` — 10s frequency-sweep, no network.
Skip gracefully without `fpcalc`, `ffmpeg`/`lame`, or QR backend.

**Current status: 109/109 passing.**

---

## Module responsibilities

| Module | Owns |
|---|---|
| `core/fingerprint.py` | `generate_fingerprint`, `fingerprint_to_bytes`, `FINGERPRINT_BYTE_LEN=120`, `fingerprint_similarity`, `FingerprintError` |
| `core/metadata.py` | `read_metadata`, `write_signature_tag`, `read_signature_tag`, `resolve_title` |
| `core/waveform.py` | `get_rms_envelope`, `compute_rms_envelope`, `generate_waveform_image` |
| `core/pixel_glyph.py` | `generate_glyph`, `decode_glyph`, `verify_glyph_against_mp3`, `render_glyph_image`, `list_luts`, `get_lut_curve` |
| `core/graphic_key.py` | `build_graphic_key`, `load_graphic_key_payload`, QR encode/decode, layout constants |
| `core/decoder.py` | `decode_graphic_key`, `verify_against_mp3` |
| `core/spectral.py` | `SpectralCodec`, `encode_field`, `decode_field` — lossless bytes↔smooth 256² DCT field (signed-glyph WIP) |
| `core/glyph.py` | `encode_glyph`, `decode_glyph`, `CAPACITY_BYTES` — ultra-smooth cohesive glyph layer (signed-glyph WIP) |
| `api/routes.py` | HTTP handlers |
| `api/schemas.py` | `.mp3` / `.png|.jpg|.jpeg` upload validation |
| `cli.py` | CLI orchestration |

---

## Signed glyph initiative (work in progress)

Designing a **signed, offline-verifiable certificate of audio authenticity** for
artists/labels: a single 256×256 glyph that is both the art and the proof.
Detailed Features 3–7 roadmap to resume from: **`docs/signed-glyph/implementation-plan.md`**.
Why / capacity math / open decisions: **`docs/signed-glyph/capacity-research.md`**.

**Locked design decisions:**
- **One canonical 256×256 glyph** (will retire the 64px-decodable + 256-display + 800×300 QR key).
- **Spectral encoding** — payload lives in **low-frequency 2D-DCT coefficients** per channel, not per pixel, so the inverse transform is a smooth gradient and *every pixel is load-bearing*. Lossless PNG only.
- **Look** — ultra-smooth atmospheric bloom (Path B): low band + universal invertible cohesion colour transform. (The coherent single-palette aurora look is **proven impossible to carry data losslessly** — routing data through a palette destroys coefficient precision.)
- **Trust model** — TOFU pinning + domain `.well-known`; embedded **MuSig2** chain (~96 B) for offline identity.

**Mechanism facts (built & tested):**
- `SpectralCodec`: centered-lattice waterfilling QIM, bits/coeff ∝ decaying amplitude envelope; whitening keystream → uniform symbols, data-independent energy. BER 0 holds only while the field stays in [0,255] (no clipping); carrier `ENV0=6000` → std ~21.
- `core/glyph.py`: band `FREQ_R=10` (ultra-smooth), **capacity 168 B**, cohesion transform `M = GI·I + (GC−GI)/3·ones`, `GC=0.9 GI=0.62`, `BASE=(70,95,125)` — clip-free over 30+ payloads.

**Phased plan & status** (each feature reviewed before the next):
1. ✅ Spectral codec core (`core/spectral.py`)
2. ✅ Ultra-smooth glyph layer + cohesion polish (`core/glyph.py`)
3. ⬜ Crypto/identity (`core/signing.py`): Ed25519/MuSig2 keys, canonical payload, embedded chain
4. ⬜ Glyph assembly + manifest (container/version/ECC; per-artist hue selector lives here)
5. ⬜ Verification ladder (integrity / chain / `.well-known` + TOFU / audio)
6. ⬜ CLI + API + UI integration
7. ⬜ Migration (retire 64/QR encode path, keep legacy decode) + docs

---

## Design constraints & gotchas

1. **PNG only for glyphs** — JPEG recompression destroys pixel data; enforced at save/decode.
2. **Manifest excluded from spiral** — 16 coords at rows 60–63, cols 60–63 must be filtered before spiral use. Off-by-one corrupts decode silently.
3. **LUT invertibility** — `_finalize_monotonic` guarantees strict bijection on 0..255.
4. **Encode/decode fingerprint window** — `DEFAULT_MAX_SECONDS=60` shared across QR and glyph paths via `generate_fingerprint`.
5. **Triplicated RGB** — fingerprint and ECC bytes stored as `(b,b,b)` per pixel.
6. **CRC32 is advisory** — reported separately from RS decode success (`verified` vs `rs_recovered`).
7. **reedsolo pin** — `reedsolo>=1.7.0`; `RSCodec(120)` returns 240-byte bytearray from `encode()`.
8. **Web UI is glyph-only** — `static/index.html` (Obsidian dark theme, Newsreader serif) exposes Generate / Decode / Verify against glyphs exclusively. It calls `/api/encode` (ignoring the `graphic_key` field), `/api/decode/glyph`, and `/api/verify/glyph`. The QR graphic-key routes (`/api/decode`, `/api/verify`) and `core/graphic_key.py` remain in the codebase but are no longer surfaced in the UI.
9. **ID3 tag is lossy** — full fingerprint in QR and glyph, not in ID3 tag.
10. **MP3 only** — no FLAC/WAV/AAC in validation or pipelines.
11. **No API auth** — Flask server is open; suitable for local/dev use.
12. **Hamming threshold hardcoded** — 0.85, not exposed via API/CLI flags.

---

## Conventions for future changes

- Bump glyph manifest `version` byte for format changes; maintain backward decode.
- Bump QR payload `"v"` for JSON schema changes; support legacy `Z1:` and plain base64.
- Keep `generate_fingerprint` parameters identical across encode/verify paths.
- Graphic key layout constants → `core/graphic_key.py`.
- Glyph layout/constants → `core/pixel_glyph.py`.
- Prefer extending `core/` for algorithm work; keep `api/` and `cli.py` thin.
- Tests use synthetic audio — no network fixtures.
- When updating API/CLI, update this file and `README.md` together.

---

## Changelog

| Date | Change |
|---|---|
| 2026-06-22 | Signed-glyph WIP: spectral codec (`core/spectral.py`, Feature 1) + ultra-smooth cohesive glyph layer (`core/glyph.py`, Feature 2); research doc `docs/signed-glyph/capacity-research.md`; +20 tests |
| 2026-06-21 | Glyph-only web UI redesign (`static/index.html`, Obsidian/Newsreader), new `/api/verify/glyph` route wiring `verify_glyph_against_mp3` |
| 2026-06-08 | Pixel glyph module (`core/pixel_glyph.py`), 800px graphic key, API/CLI integration, 4 new tests, `fingerprint_bytes`, `get_rms_envelope` |
| 2026-06-08 | Initial `claude.md` (pre-glyph project brief) |
| prior | QR capacity fixes, 600px graphic key, static web UI |
