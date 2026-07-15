# Feature 3 — Crypto/Identity (`core/signing.py`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TDD a thin Ed25519 signing module (`core/signing.py`) with four public functions: `generate_keypair`, `sign`, `verify`, and `canonical_message`.

**Architecture:** Pure functions over raw bytes — no classes, no state. The `cryptography` (PyCA) library handles all Ed25519 primitives. `canonical_message` uses `struct.pack` for a fixed big-endian binary layout (56 bytes) that both sign and verify sides call identically.

**Tech Stack:** Python 3.13, `cryptography>=44.0.0`, `pytest`

## Global Constraints

- Ed25519 private key: 32 bytes raw. Public key: 32 bytes raw. Signature: 64 bytes.
- `verify` must never raise — catch all exceptions and return `False`.
- `canonical_message` format string `">B16sHBI32s"` is fixed; 56 bytes total, big-endian.
- TDD: write the failing test, confirm it fails, then implement — never skip the red step.
- Run all tests after each task: `source .venv/bin/activate && pytest tests/ -q`
- Commit after each task passes.
- Spec: `docs/superpowers/specs/2026-07-15-signing-feature3-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `requirements.txt` | Modify | Add `cryptography>=44.0.0` |
| `core/signing.py` | Create | All four public functions |
| `tests/test_signing.py` | Create | All signing tests |

---

## Task 1: Dependency + `generate_keypair`

**Files:**
- Modify: `requirements.txt`
- Create: `core/signing.py`
- Create: `tests/test_signing.py`

**Interfaces:**
- Produces: `generate_keypair() -> tuple[bytes, bytes]` — `(priv_32B, pub_32B)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signing.py`:

```python
from core.signing import generate_keypair


def test_generate_keypair_sizes():
    priv, pub = generate_keypair()
    assert len(priv) == 32
    assert len(pub) == 32


def test_generate_keypair_returns_bytes():
    priv, pub = generate_keypair()
    assert isinstance(priv, bytes)
    assert isinstance(pub, bytes)


def test_generate_keypair_unique():
    priv1, pub1 = generate_keypair()
    priv2, pub2 = generate_keypair()
    assert priv1 != priv2
    assert pub1 != pub2
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_signing.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.signing'`

- [ ] **Step 3: Add dependency and install**

Add to `requirements.txt` (after the existing deps, before the `# Testing` comment):

```
cryptography>=44.0.0
```

Then install:

```bash
source .venv/bin/activate && pip install cryptography>=44.0.0
```

Expected output includes: `Successfully installed cryptography-...`

- [ ] **Step 4: Create `core/signing.py` with `generate_keypair`**

```python
"""Ed25519 signing primitives for the signed-glyph identity layer."""

from __future__ import annotations

import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes), each 32 bytes raw."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_signing.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Run full suite to confirm no regressions**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all existing tests pass + 3 new.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt core/signing.py tests/test_signing.py
git commit -m "feat: add Ed25519 keypair generation (Feature 3)"
```

---

## Task 2: `sign` and `verify`

**Files:**
- Modify: `core/signing.py`
- Modify: `tests/test_signing.py`

**Interfaces:**
- Consumes: `generate_keypair() -> tuple[bytes, bytes]` (Task 1)
- Produces:
  - `sign(message: bytes, priv_key: bytes) -> bytes` — 64-byte signature
  - `verify(message: bytes, sig: bytes, pub_key: bytes) -> bool` — never raises

- [ ] **Step 1: Add failing tests**

Append to `tests/test_signing.py`:

```python
from core.signing import generate_keypair, sign, verify


def test_sign_returns_64_bytes():
    priv, pub = generate_keypair()
    sig = sign(b"hello", priv)
    assert len(sig) == 64
    assert isinstance(sig, bytes)


def test_roundtrip():
    priv, pub = generate_keypair()
    message = b"audio identity test message"
    sig = sign(message, priv)
    assert verify(message, sig, pub) is True


def test_tampered_message():
    priv, pub = generate_keypair()
    message = b"audio identity test message"
    sig = sign(message, priv)
    tampered = bytes([message[0] ^ 0xFF]) + message[1:]
    assert verify(tampered, sig, pub) is False


def test_tampered_sig():
    priv, pub = generate_keypair()
    message = b"audio identity"
    sig = sign(message, priv)
    tampered_sig = bytes([sig[0] ^ 0xFF]) + sig[1:]
    assert verify(message, tampered_sig, pub) is False


def test_wrong_pubkey():
    priv, _ = generate_keypair()
    _, other_pub = generate_keypair()
    message = b"audio identity"
    sig = sign(message, priv)
    assert verify(message, sig, other_pub) is False


def test_verify_never_raises():
    assert verify(b"msg", b"x" * 64, b"y" * 32) is False
    assert verify(b"msg", b"bad", b"key") is False
    assert verify(b"", b"", b"") is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_signing.py -v
```

Expected: 6 new tests fail with `ImportError: cannot import name 'sign'`.

- [ ] **Step 3: Add `sign` and `verify` to `core/signing.py`**

The complete file after this step:

```python
"""Ed25519 signing primitives for the signed-glyph identity layer."""

from __future__ import annotations

import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes), each 32 bytes raw."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes


def sign(message: bytes, priv_key: bytes) -> bytes:
    """Sign message with Ed25519 private key. Returns 64-byte signature."""
    key = Ed25519PrivateKey.from_private_bytes(priv_key)
    return key.sign(message)


def verify(message: bytes, sig: bytes, pub_key: bytes) -> bool:
    """Verify Ed25519 signature. Returns False on any failure, never raises."""
    try:
        key = Ed25519PublicKey.from_public_bytes(pub_key)
        key.verify(sig, message)
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_signing.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/signing.py tests/test_signing.py
git commit -m "feat: add Ed25519 sign and verify (Feature 3)"
```

---

## Task 3: `canonical_message` + integration

**Files:**
- Modify: `core/signing.py`
- Modify: `tests/test_signing.py`

**Interfaces:**
- Consumes: `sign`, `verify` (Task 2); `generate_keypair` (Task 1)
- Produces:
  ```python
  def canonical_message(
      *,
      version: int,
      fingerprint_digest: bytes,  # exactly 16 bytes
      duration: int,              # uint16, seconds
      bpm: int,                   # uint8, 0 if unknown
      timestamp: int,             # uint32, unix epoch
      pub_key: bytes,             # exactly 32 bytes
  ) -> bytes:                     # always 56 bytes, big-endian
  ```

- [ ] **Step 1: Add failing tests**

Append to `tests/test_signing.py`:

```python
from core.signing import generate_keypair, sign, verify, canonical_message


def test_canonical_message_length():
    _, pub = generate_keypair()
    msg = canonical_message(
        version=1,
        fingerprint_digest=b"\x00" * 16,
        duration=213,
        bpm=0,
        timestamp=1720000000,
        pub_key=pub,
    )
    assert len(msg) == 56


def test_canonical_message_determinism():
    _, pub = generate_keypair()
    kwargs = dict(
        version=1,
        fingerprint_digest=b"\xab" * 16,
        duration=180,
        bpm=120,
        timestamp=1720000000,
        pub_key=pub,
    )
    assert canonical_message(**kwargs) == canonical_message(**kwargs)


def test_canonical_message_field_change():
    _, pub = generate_keypair()
    base = dict(
        version=1,
        fingerprint_digest=b"\x01" * 16,
        duration=180,
        bpm=120,
        timestamp=1720000000,
        pub_key=pub,
    )
    original = canonical_message(**base)
    _, other_pub = generate_keypair()
    assert canonical_message(**{**base, "version": 2}) != original
    assert canonical_message(**{**base, "fingerprint_digest": b"\x02" * 16}) != original
    assert canonical_message(**{**base, "duration": 181}) != original
    assert canonical_message(**{**base, "bpm": 121}) != original
    assert canonical_message(**{**base, "timestamp": 1720000001}) != original
    assert canonical_message(**{**base, "pub_key": other_pub}) != original


def test_sign_verify_with_canonical_message():
    priv, pub = generate_keypair()
    msg = canonical_message(
        version=1,
        fingerprint_digest=b"\xde\xad" * 8,
        duration=213,
        bpm=128,
        timestamp=1720000000,
        pub_key=pub,
    )
    sig = sign(msg, priv)
    assert verify(msg, sig, pub) is True
    tampered = bytes([msg[0] ^ 0x01]) + msg[1:]
    assert verify(tampered, sig, pub) is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_signing.py -v
```

Expected: 4 new tests fail with `ImportError: cannot import name 'canonical_message'`.

- [ ] **Step 3: Add `canonical_message` to `core/signing.py`**

The complete final file:

```python
"""Ed25519 signing primitives for the signed-glyph identity layer."""

from __future__ import annotations

import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes), each 32 bytes raw."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_bytes, pub_bytes


def sign(message: bytes, priv_key: bytes) -> bytes:
    """Sign message with Ed25519 private key. Returns 64-byte signature."""
    key = Ed25519PrivateKey.from_private_bytes(priv_key)
    return key.sign(message)


def verify(message: bytes, sig: bytes, pub_key: bytes) -> bool:
    """Verify Ed25519 signature. Returns False on any failure, never raises."""
    try:
        key = Ed25519PublicKey.from_public_bytes(pub_key)
        key.verify(sig, message)
        return True
    except Exception:
        return False


def canonical_message(
    *,
    version: int,
    fingerprint_digest: bytes,
    duration: int,
    bpm: int,
    timestamp: int,
    pub_key: bytes,
) -> bytes:
    """Deterministic big-endian binary serialisation of the signed fields.

    Format ">B16sHBI32s": version(1) + digest(16) + duration(2) + bpm(1)
    + timestamp(4) + pub_key(32) = 56 bytes total.
    """
    return struct.pack(
        ">B16sHBI32s",
        version,
        fingerprint_digest,
        duration,
        bpm,
        timestamp,
        pub_key,
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_signing.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all tests pass (92 existing + 13 new = 105 total).

- [ ] **Step 6: Commit**

```bash
git add core/signing.py tests/test_signing.py
git commit -m "feat: add canonical_message and integration tests (Feature 3 complete)"
```
