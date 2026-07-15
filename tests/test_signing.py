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
