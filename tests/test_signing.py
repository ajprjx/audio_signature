from core.signing import generate_keypair, sign, verify


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
