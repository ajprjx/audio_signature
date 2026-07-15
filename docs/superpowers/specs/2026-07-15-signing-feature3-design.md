# Feature 3 — Crypto / Identity (`core/signing.py`)

> Spec date: 2026-07-15. Part of the signed-glyph initiative.
> Read with `docs/signed-glyph/implementation-plan.md` and `docs/signed-glyph/capacity-research.md`.

## Goal

A thin, well-tested crypto module that the rest of the signed-glyph stack can build on.
Provides Ed25519 keypair generation, signing, verification, and deterministic message
serialisation. Everything else (container layout, glyph assembly, verification ladder)
is deferred to Features 4–7.

## Decisions

- **Signing scheme:** Ed25519 via `cryptography` (PyCA). Battle-tested, no footguns,
  deterministic signing, 32B pubkey + 64B sig = 96B total.
- **Signing topology:** Artist-only for now. MuSig2 / label chain deferred; no abstract
  interface needed (YAGNI — a future swap is a concrete change to this file).
- **Pubkey storage:** 32B pubkey embedded in the glyph (offline verification). Feature 5
  cross-checks against `.well-known`.
- **Library:** `cryptography>=44.0.0`. No other new dependencies.

## Module: `core/signing.py`

Four public functions, no classes.

### `generate_keypair() -> tuple[bytes, bytes]`

Returns `(private_key_bytes, public_key_bytes)`, each 32 bytes raw.

Implementation: `Ed25519PrivateKey.generate()`, serialised with
`private_bytes(Raw, Raw, NoEncryption)` and `public_key().public_bytes(Raw, Raw)`.

### `sign(message: bytes, priv_key: bytes) -> bytes`

Returns a 64-byte Ed25519 signature. Signing is deterministic — same key + message
always produces the same signature (no nonce).

Implementation: reconstruct `Ed25519PrivateKey.from_private_bytes(priv_key)`,
call `.sign(message)`.

### `verify(message: bytes, sig: bytes, pub_key: bytes) -> bool`

Returns `True` if the signature is valid, `False` on any failure. Never raises.

Implementation: reconstruct `Ed25519PublicKey.from_public_bytes(pub_key)`, call
`.verify(sig, message)`, catch `InvalidSignature` and `ValueError`.

### `canonical_message(...) -> bytes`

Deterministic fixed-order binary serialisation of the fields that get signed.
Keyword-only arguments:

| Argument | Type | Struct | Bytes | Notes |
|---|---|---|---|---|
| `version` | `int` | `B` | 1 | Container format version |
| `fingerprint_digest` | `bytes` | `16s` | 16 | Truncated SHA-256 of chromaprint |
| `duration` | `int` | `H` | 2 | Track duration in seconds (uint16 BE) |
| `bpm` | `int` | `B` | 1 | BPM, 0 if unknown |
| `timestamp` | `int` | `I` | 4 | Unix epoch (uint32 BE) |
| `pub_key` | `bytes` | `32s` | 32 | Artist Ed25519 pubkey |

Format string: `">B16sHBI32s"` — big-endian, 56 bytes total.

Feature 4 will extend this struct with `flags` and `style_id` when it finalises the
container layout.

## Tests: `tests/test_signing.py`

All tests are self-contained (no fixtures, no MP3s, no disk I/O).

| Test | What it asserts |
|---|---|
| `test_generate_keypair_sizes` | priv and pub are each exactly 32 bytes |
| `test_sign_returns_64_bytes` | signature length is 64 |
| `test_roundtrip` | sign → verify returns True |
| `test_tampered_message` | flip one byte in message → verify returns False |
| `test_tampered_sig` | flip one byte in sig → verify returns False |
| `test_wrong_pubkey` | different keypair's pubkey → verify returns False |
| `test_verify_never_raises` | garbage bytes for sig/key → False, no exception |
| `test_canonical_message_determinism` | same fields twice → identical bytes |
| `test_canonical_message_length` | output is exactly 56 bytes |
| `test_canonical_message_field_change` | each field change produces different output |
| `test_sign_verify_with_canonical_message` | full round-trip using canonical_message |

## Dependency

Add to `requirements.txt`:

```
cryptography>=44.0.0
```

No other files change in Feature 3.

## Capacity impact

Crypto payload in the glyph: 32B pubkey + 64B sig = 96B. With `CAPACITY_BYTES = 168`
(at `FREQ_R = 10`), this leaves 72B for the remaining container fields (fingerprint
digest, metadata, CRC). Comfortable; no band change needed for Feature 3.

## Out of scope (deferred)

- Container struct layout (`pack_container` / `unpack_container`) → Feature 4
- Per-artist style/colour → Feature 4
- Verification ladder, TOFU pinning, `.well-known` → Feature 5
- Label co-signing / MuSig2 → not planned; revisit if needed
