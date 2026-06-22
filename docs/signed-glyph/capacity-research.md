# Signed Glyph — Capacity Research (fit optimization)

> Status: research notes, 2026-06-21. Mechanism validated by spike; not yet implemented.
> Goal: embed an offline-verifiable artist→label signature chain inside a **256×256
> ultra-smooth spectral glyph** without spoiling the look.

## Decisions locked

- **256×256 canonical glyph** (retires the 64px decodable + 256 display + QR graphic key into one artifact).
- **Spectral encoding**: payload lives in **low-frequency 2D-DCT coefficients** (per color channel),
  not per-pixel. Inverse transform → smooth gradient. **Every pixel is load-bearing.** No seal/frame/text.
- **Look**: ultra-smooth low-frequency field → curated per-artist multi-stop **palette** (aurora/ember/tide…).
  Color is load-bearing; same artist = same palette/visual family, each track = distinct bloom.
- **Trust model**: TOFU pinning + domain `.well-known` (decentralized, no registry to operate).
- **Encoding proven**: lossless PNG round-trip at **BER = 0** when the field stays inside [0,255]
  (clipping is the enemy; spatial std ≤ ~27 keeps clip ≈ 0). Per-coefficient noise from 8-bit
  rounding ≈ 0.3 std.

## The capacity ceiling (the core constraint)

Power-constrained channel: smoothness caps the usable frequency band, which caps the number of
modes; contrast caps coefficient power; 8-bit rounding is the noise. Shannon ceiling
(3 channels, spatial std 27, equal power, noise var 0.09):

| Freq band (u+v ≤) | coeffs/ch | ceiling | smoothness |
|---|---|---|---|
| 8  | 44  | ~194 B | ultra-smooth |
| 10 | 65  | ~280 B | ultra-smooth (the pretty samples) |
| 12 | 90  | ~380 B | smooth |
| 16 | 152 | ~619 B | smooth-ish (slightly busier) |
| 20 | 230 | ~912 B | structured |

**Finding:** the ultra-smooth band tops out near **~280 B even in theory.** A naive full chain
(2× Ed25519 sig 64 + 2× pubkey 32 + 120 B fingerprint + meta ≈ ~400+ B) **does not fit ultra-smooth.**
Naive *uniform* multi-bit QIM is far worse (BER 0 only to ~48 B at FREQ≤10) because it over-asks the
small high-frequency coefficients. → Two fronts: **shrink the payload** and **bit-load properly**.

## Solution space

### A. Shrink the payload (preserves max smoothness — preferred)

1. **Signature/key aggregation — MuSig2 (BIP-327 / Schnorr secp256k1).**
   Artist + label co-sign → **one 32 B aggregate key + one 64 B signature = 96 B** for the whole chain
   (vs ~192 B sequential). The aggregate key is the identity anchor resolved via `.well-known`.
   - Alt: **BLS12-381** aggregation (48 B G1 sig / 48 B agg key) — also constant-size, but needs a
     pairing library; heavier dependency than secp256k1.
   - Trade: MuSig2 is an **interactive 2-round** co-signing protocol (artist+label both online per track).
   - Non-interactive alt: **sequential certs** (label signs artist key once, offline; artist signs each
     track alone) — simpler ops, ~192 B, pushes to FREQ≤14.
2. **No stored pubkeys.** The aggregate key *is* the anchor (resolve who-it-is via `.well-known`),
   so individual artist/label pubkeys need not be embedded. (If using ECDSA secp256k1 instead of
   Schnorr, public-key *recovery* from signature saves 32 B/key — but Schnorr/BIP-340 has no recovery.)
3. **Compact fingerprint.** Store a 16–32 B fingerprint digest for offline integrity; resolve the full
   chromaprint via `.well-known` for fuzzy audio-match. Trade: full **offline** audio-match fidelity.
4. **Minimal ECC.** Lossless PNG ⇒ BER ≈ 0; reserve ECC only as clip/robustness margin, not bulk parity.

### B. Use the channel better

5. **Waterfilling bit-loading.** Allocate bits per coefficient ∝ amplitude (like JPEG quant tables)
   instead of uniform. Closes most of the gap to the Shannon ceiling (~5× over naive uniform).
   This is the single biggest practical-capacity win and the first thing to build.
6. **Perceptual color power allocation.** Put more energy in chroma (OKLab/CIELAB a,b) where the eye
   tolerates variation at equal perceived smoothness. Gain is logarithmic (modest) but real.
7. **Graceful frequency fallback.** If realized capacity underdelivers, widen to FREQ≤12–14
   (380–~500 B ceiling) — still smooth, the look degrades gradually, not catastrophically.

## Recommended target budget (~170 B → fits FREQ≤10–12 with bit-loading)

| Field | Bytes |
|---|---|
| MuSig2 aggregate key (identity anchor) | 32 |
| MuSig2 aggregate signature (artist+label) | 64 |
| Fingerprint digest (offline integrity) | 32 |
| Metadata: duration, timestamp, bpm, version/flags | ~14 |
| Light ECC / clip margin (~20%) | ~30 |
| **Total** | **~172** |

~172 B sits under the ultra-smooth ceiling (~280 B) with headroom for bit-loading inefficiency.
If offline audio-match needs the full fingerprint, carry more fp bytes and accept FREQ≤12–14.

## Open decisions (for "later")

- **Ops vs size:** interactive MuSig2 co-signing vs non-interactive sequential certs (~96 B vs ~192 B).
- **Offline audio-match fidelity:** fingerprint digest (compact, online for full match) vs fuller fp (costs smoothness).
- **Implement waterfilling bit-loading + verify BER 0** at the target budget before committing the band.
- **Color space:** RGB vs OKLab for the power allocation.

## Spike artifacts

- `/tmp/spectral_spike.py` — proves lossless DCT-QIM round-trip (BER 0 at std ≤ 28).
- `/tmp/spectral_palette.py` — the locked ultra-smooth palette-bloom look.
- Capacity/BER numbers above reproduced from the capacity calc spike.

## Sources

- BIP-327 MuSig2: https://bips.dev/327/ , https://github.com/bitcoin/bips/blob/master/bip-0327.mediawiki
- BIP-340 Schnorr: https://bips.dev/340/
- Python Schnorr/MuSig: https://github.com/BitPolito/schnorr-sig
