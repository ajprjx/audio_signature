"""Chromaprint fingerprinting logic.

Uses pyacoustid (which shells out to the ``fpcalc`` binary from
libchromaprint-tools) to compute acoustic fingerprints of MP3 files.
"""

from __future__ import annotations

import ctypes.util
import glob
import hashlib
import os
import shutil

try:
    import acoustid
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "pyacoustid is required. Install with `pip install pyacoustid`."
    ) from exc


def _load_chromaprint():
    """Import the chromaprint ctypes binding, helping it find the shared lib.

    Core fingerprinting uses the ``fpcalc`` binary, so the chromaprint shared
    library is optional — only the Hamming-distance similarity fallback needs
    ``decode_fingerprint``. We try a plain import first, then preload the
    library from common Homebrew/system locations if ctypes can't find it.
    """
    try:
        import chromaprint  # noqa: WPS433

        return chromaprint
    except ImportError:
        pass

    # The binding dlopen's the library by leaf name (e.g. "libchromaprint.1.dylib"),
    # which doesn't search Homebrew/non-standard dirs, and DYLD_* env vars can't be
    # injected at runtime. So we briefly wrap ctypes.CDLL to redirect that leaf name
    # to an absolute path we locate ourselves, then import.
    candidates: list[str] = []
    found = ctypes.util.find_library("chromaprint")
    if found:
        candidates.append(found)
    for base in ("/opt/homebrew/lib", "/usr/local/lib", "/usr/lib", "/lib"):
        candidates += sorted(glob.glob(os.path.join(base, "libchromaprint*")))

    abs_path = next((p for p in candidates if os.path.exists(p)), None)
    if abs_path is None:
        return None

    real_cdll = ctypes.CDLL

    def _patched_cdll(name, *a, **kw):
        if name and os.path.basename(str(name)).startswith("libchromaprint"):
            name = abs_path
        return real_cdll(name, *a, **kw)

    ctypes.CDLL = _patched_cdll  # type: ignore[assignment]
    try:
        import chromaprint  # noqa: WPS433

        return chromaprint
    except ImportError:
        return None
    finally:
        ctypes.CDLL = real_cdll  # type: ignore[assignment]


chromaprint = _load_chromaprint()


class FingerprintError(RuntimeError):
    """Raised when fingerprinting fails."""


def ensure_fpcalc_available() -> None:
    """Raise a clear error if the ``fpcalc`` system binary is not on PATH."""
    if shutil.which("fpcalc") is None:
        raise FingerprintError(
            "The 'fpcalc' binary was not found on PATH. Install it with "
            "`apt-get install -y libchromaprint-tools` (Debian/Ubuntu) or "
            "`brew install chromaprint` (macOS)."
        )


def generate_fingerprint(mp3_path: str) -> dict:
    """Fingerprint an MP3 with chromaprint.

    Returns a dict with the raw chromaprint string, duration in seconds, and a
    short (16 hex char) sha256 hash of the fingerprint for compact identity.
    """
    ensure_fpcalc_available()
    try:
        duration, fingerprint = acoustid.fingerprint_file(mp3_path)
    except acoustid.FingerprintGenerationError as exc:
        raise FingerprintError(f"Failed to fingerprint {mp3_path}: {exc}") from exc

    # acoustid returns the fingerprint as bytes; normalize to a str.
    if isinstance(fingerprint, bytes):
        fingerprint_str = fingerprint.decode("ascii")
    else:
        fingerprint_str = fingerprint

    fingerprint_hash = hashlib.sha256(
        fingerprint_str.encode("ascii")
    ).hexdigest()[:16]

    return {
        "fingerprint": fingerprint_str,
        "duration": round(float(duration), 1),
        "fingerprint_hash": fingerprint_hash,
    }


def _decode_fingerprint_bits(fp: str) -> list[int]:
    """Decode a chromaprint string into a flat list of 32-bit integers."""
    if chromaprint is None:
        raise RuntimeError("libchromaprint not available for fingerprint decoding")
    raw = fp.encode("ascii") if isinstance(fp, str) else fp
    ints, _version = chromaprint.decode_fingerprint(raw)
    return list(ints)


def _hamming_similarity(a: list[int], b: list[int]) -> float:
    """Similarity (0..1) of two int lists via bitwise Hamming distance."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    total_bits = n * 32
    diff_bits = 0
    for i in range(n):
        diff_bits += bin(a[i] ^ b[i]).count("1")
    # Penalize length mismatch by counting the extra frames as fully different.
    extra = abs(len(a) - len(b))
    diff_bits += extra * 32
    total_bits += extra * 32
    if total_bits == 0:
        return 0.0
    return 1.0 - (diff_bits / total_bits)


def fingerprints_match(fp1: str, fp2: str, threshold: float = 0.85) -> bool:
    """Return True if two chromaprint fingerprints are similar enough.

    Tries ``acoustid.compare_fingerprints`` when available, otherwise falls
    back to a Hamming-distance similarity over the decoded bits.
    """
    similarity = fingerprint_similarity(fp1, fp2)
    return similarity >= threshold


def fingerprint_similarity(fp1: str, fp2: str) -> float:
    """Return a 0..1 similarity score between two chromaprint fingerprints."""
    if fp1 == fp2:
        return 1.0
    try:
        bits1 = _decode_fingerprint_bits(fp1)
        bits2 = _decode_fingerprint_bits(fp2)
        return _hamming_similarity(bits1, bits2)
    except Exception:
        # If decoding fails, fall back to a coarse string comparison.
        if not fp1 or not fp2:
            return 0.0
        shorter, longer = sorted((fp1, fp2), key=len)
        matches = sum(1 for a, b in zip(shorter, longer) if a == b)
        return matches / len(longer)
