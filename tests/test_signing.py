from core.signing import generate_keypair, sign, verify, canonical_message


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
