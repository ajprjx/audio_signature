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
