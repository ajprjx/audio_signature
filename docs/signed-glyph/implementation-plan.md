# Signed Glyph — Implementation Plan (Features 3–7)

> Resume doc, last updated 2026-06-22. Read with `docs/signed-glyph/capacity-research.md`
> (the why/capacity math) and the "Signed glyph initiative" section in `CLAUDE.md`.

## How to resume

**Goal:** one 256×256 glyph that is both the art and an offline-verifiable certificate
of audio authenticity for artists/labels.

**Working style (keep doing this):**
- **TDD** (red → green → refactor): no production code without a failing test first.
- **One feature at a time, then STOP for review** before starting the next.
- For aesthetic checks, render real samples and view them (a visual-companion server
  was used: `superpowers/.../brainstorming/scripts/start-server.sh --project-dir .`,
  write HTML into its `content/` dir with base64-embedded PNGs).
- Use the project venv: `source .venv/bin/activate`. Run `pytest tests/ -q`.

**Built so far (Features 1–2, all green, 109 tests):**
- `core/spectral.py` — `SpectralCodec(freq_r=…)`: lossless bytes ↔ smooth 256² RGB DCT
  field. Waterfilling QIM (bits/coeff ∝ amplitude envelope), whitening keystream,
  centered lattice. `encode_to_field`/`decode_from_field` expose the pre-round float
  field for transforms. Default band R=18 → 494 B.
- `core/glyph.py` — `encode_glyph`/`decode_glyph`, band **R=10**, **CAPACITY_BYTES=168**,
  ultra-smooth; universal invertible cohesion colour transform (`GC=0.9, GI=0.62,
  BASE=(70,95,125)`) → moody teal/indigo bloom.

## Hard invariants (do not break)

- **Lossless PNG only.** Any lossy recompression destroys the payload.
- **BER 0 requires the field stays within [0,255] — no clipping.** Every transform/
  param change must be verified clip-free over ≥30 random full-capacity payloads.
- **Capacity is 168 B at R=10.** The whole signed container must fit. If it doesn't,
  the cleanest lever is nudging `glyph.FREQ_R` to 11–12 (≈210–290 B) — still smooth;
  re-tune cohesion clip-safety after. Decide in Feature 4.
- Per-artist colour (hue/base selector) is **plaintext in the payload**, applied at
  render time; decode must recover it before the cohesion inverse if it's per-artist.
  (Today's cohesion transform is universal/fixed — fine until Feature 4.)

## The signed container (the ≤168 B payload `encode_glyph` carries)

`encode_glyph(payload)` is byte-agnostic; Feature 4 defines `payload` as this container.
Recommended layout (tune exact widths in Feature 4; keep total ≤ capacity):

| Field | Bytes | Notes |
|---|---|---|
| version | 1 | container format version |
| flags | 1 | signed?, has-chain?, ecc-level, … |
| style/hue id | 1 | per-artist palette/base selector (Feature 4 colour) |
| fingerprint digest | 16 | truncated SHA-256 of chromaprint (offline integrity) |
| duration | 2 | uint16 seconds |
| bpm | 1 | 0 if unknown |
| timestamp | 4 | unix epoch |
| domain / identity pointer | ~16–24 | for `.well-known` resolution (plaintext) |
| MuSig2 aggregate pubkey | 32 | identity anchor (resolved via `.well-known`) |
| MuSig2 aggregate signature | 64 | artist+label countersignature |
| CRC32 | 4 | integrity/error detection |
| RS parity | remainder | light ECC; lossless ⇒ BER 0, so this is margin |

Core ≈ 142–150 B + ECC. At 168 B this is tight; trimming the domain or bumping the
band may be needed. **Signed message** (what MuSig2 signs) = all fields *except* the
signature and parity (canonical, fixed-order binary — not JSON).

## Feature 3 — Crypto / identity (`core/signing.py`)

TDD a thin module over a vetted library (research: **MuSig2 / BIP-327** on secp256k1;
Python `BitPolito/schnorr-sig` or similar — verify availability, else fall back to
Ed25519 sequential certs, see open decisions). Public API roughly:

- `generate_keypair() -> (priv, pub)` (raw bytes).
- `canonical_message(fields: dict) -> bytes` — deterministic serialization of the
  signed container fields (must match exactly on sign + verify).
- `aggregate_key(pubkeys) -> agg_pub` and a co-sign flow producing one 64 B signature.
- `sign(message, signers) -> sig` / `verify(message, sig, agg_pub) -> bool`.
- Keep individual-key Ed25519 sign/verify too (artist-only, unsigned-label case).

Tests: keygen determinism/sizes; sign→verify true; tampered message → false; wrong key
→ false; aggregate of artist+label verifies under the aggregate key.

Add `cryptography` (and the Schnorr/MuSig lib) to `requirements.txt`.

## Feature 4 — Glyph assembly + manifest/container (`core/signed_glyph.py`)

- Define the container struct above: `pack_container(...) -> bytes`,
  `unpack_container(bytes) -> dict` (version-dispatched), `CRC32`, RS via `reedsolo`.
- `generate_signed_glyph(mp3, out_png, signers, style=…)`:
  fingerprint → digest → build container → sign → `glyph.encode_glyph` → PNG.
- `decode_signed_glyph(png) -> dict` (unpack, CRC, ECC).
- **Wire per-artist colour here**: the `style/hue id` selects the cohesion BASE/gains;
  generalize `glyph.encode_glyph`/`decode_glyph` to take a style id (default = current
  universal look). Verify clip-safe + BER 0 per style.
- **Finalize the capacity budget** here; bump `FREQ_R` if the container overflows 168 B.

Tests: container pack/unpack round-trip; full mp3→glyph→decode; CRC catches corruption;
each style id round-trips clip-free; version dispatch.

## Feature 5 — Verification ladder (`core/glyph_verify.py`)

Independent rungs, graceful degradation:
1. **Integrity** (offline): MuSig2 `verify(canonical_message, sig, agg_pub)`.
2. **Chain** (offline, from embedded chain): label countersignature over artist key.
3. **Anchor**: is `agg_pub` trusted? → **TOFU pinning store** (local JSON) +
   **`.well-known`** fetch (`https://<domain>/.well-known/audio-signature/keys.json`)
   listing keys; online, short TTL, revocation = key removed.
4. **Audio** (optional): re-fingerprint mp3, compare to embedded digest; reuse the
   existing chromaprint **similarity** path (Hamming ≥ 0.85) for transcode tolerance.

Return a structured verdict with per-rung status. Tests with a local fake `.well-known`
and an in-memory pin store; positive + negative (tamper, wrong signer, unknown domain).

## Feature 6 — CLI + API + UI

- CLI: `genkey`, `encode --sign-with <key> [--countersign <label-key>] [--style]`,
  `verify-glyph <png> [<mp3>] [--pubkey/--domain]`, `publish-keys` (emit `.well-known`).
- API: extend `/api/encode` (sign params), `/api/decode/glyph` + `/api/verify/glyph`
  (return the verification-ladder verdict). Keep handlers thin.
- UI (`static/index.html`, glyph-only Obsidian/Newsreader): show the signed bloom and a
  clear ✓/⚠ per-rung verdict (Integrity / Identity / Audio). Update README **here**.

## Feature 7 — Migration + docs

- Make the signed 256² spectral glyph the canonical artifact. Encode path stops emitting
  the 64px decodable + 256 display + 800×300 QR key; **keep legacy *decode*** for old
  64px glyphs (manifest version dispatch in `core/pixel_glyph.py`).
- Update `CLAUDE.md` + `README.md` together; refresh performance/test tables.

## Open decisions (decide as you reach them)

1. **MuSig2 (interactive 2-round co-sign, ~96 B) vs sequential certs (non-interactive,
   ~192 B).** MuSig2 is compact but artist+label must co-sign each track; sequential is
   simpler ops but bigger (would push the band up). Start by checking the Python lib
   maturity in Feature 3; if weak, sequential Ed25519 certs are the safe fallback.
2. **Offline audio-match fidelity**: 16 B digest (need network for full fuzzy match) vs
   embedding more fingerprint bytes (costs capacity → higher band → less smooth).
3. **ECC level**: lossless ⇒ BER 0, so minimal RS parity (or CRC-only) maximizes payload.

## Key references

- Why/capacity math: `docs/signed-glyph/capacity-research.md`
- Status + locked decisions: `CLAUDE.md` → "Signed glyph initiative"
- Built code: `core/spectral.py`, `core/glyph.py`; tests `tests/test_spectral.py`,
  `tests/test_glyph.py`
- MuSig2: BIP-327 (https://bips.dev/327/), BIP-340 (https://bips.dev/340/),
  Python https://github.com/BitPolito/schnorr-sig
