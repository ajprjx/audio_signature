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
