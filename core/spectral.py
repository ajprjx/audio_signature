"""Spectral codec: lossless bytes <-> a smooth 256x256 RGB field.

Payload is carried in the low-frequency 2D-DCT coefficients of each color
channel (not per pixel), so the inverse transform is a smooth gradient and
*every pixel is load-bearing*. Each coefficient carries several bits via a
centered uniform lattice whose level count is allocated by a decaying amplitude
envelope (waterfilling): low frequencies get larger amplitude and more bits.

Robustness comes from lossless PNG: the only channel noise is 8-bit spatial
rounding, which perturbs each coefficient by < ~0.7. Lattice steps are kept
above ``STEP_MIN`` so symbols recover exactly (BER 0) as long as the field
stays within [0, 255] (no clipping).
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn

N = 256
FREQ_R = 18          # low-frequency band: keep u+v <= FREQ_R (smoothness)
STEP_MIN = 3.2       # min lattice step (must exceed ~2x the 0.7 rounding noise)
BMAX = 7             # cap bits per coefficient
ENV0 = 6000.0        # amplitude envelope scale (tuned for std ~21, no clipping)
DC = 128.0 * N       # mean ~128
_HEADER_BITS = 16    # uint16 payload length prefix


def _plan():
    """Per-channel coefficient plan: (u, v, bits, step) via waterfilling."""
    plan = []
    for u in range(FREQ_R + 1):
        for v in range(FREQ_R + 1 - u):
            if (u, v) == (0, 0):
                continue
            amp = ENV0 / (1.0 + (u + v))
            bits = int(np.floor(np.log2(max(1.0, 2.0 * amp / STEP_MIN))))
            bits = min(BMAX, bits)
            if bits < 1:
                continue
            levels = 1 << bits
            step = 2.0 * amp / levels       # >= STEP_MIN by construction
            plan.append((u, v, bits, step))
    plan.sort(key=lambda c: (c[0] + c[1], c[0], c[1]))
    return plan


PLAN = _plan()
_BITS_PER_CHANNEL = sum(b for _, _, b, _ in PLAN)
TOTAL_BITS = _BITS_PER_CHANNEL * 3
CAPACITY_BYTES = (TOTAL_BITS - _HEADER_BITS) // 8

# Whitening keystream: XORed over the payload + padding so the symbol stream is
# uniform regardless of content. Keeps energy data-independent (no clipping
# bias) and makes the rendered field look the same statistically for any input.
_FULL_BYTES = (TOTAL_BITS + 7) // 8
_KEYSTREAM = np.random.default_rng(0x5A17).integers(0, 256, _FULL_BYTES).astype(np.uint8)


def _bits_to_symbols(bits, plan):
    out, pos = [], 0
    for _, _, b, _ in plan:
        sym = 0
        for _ in range(b):
            sym = (sym << 1) | int(bits[pos]); pos += 1
        out.append(sym)
    return out, pos


def encode_field(payload: bytes) -> Image.Image:
    """Encode bytes into a 256x256 RGB field. Raises ValueError if too large."""
    if len(payload) > CAPACITY_BYTES:
        raise ValueError(
            f"payload {len(payload)}B exceeds capacity {CAPACITY_BYTES}B"
        )
    data = np.frombuffer(
        len(payload).to_bytes(2, "big") + bytes(payload), dtype=np.uint8
    )
    buf = _KEYSTREAM.copy()
    buf[: data.size] ^= data
    bits = np.unpackbits(buf)[:TOTAL_BITS]

    per_ch = _BITS_PER_CHANNEL
    chans = []
    for ch in range(3):
        syms, _ = _bits_to_symbols(bits[ch * per_ch:(ch + 1) * per_ch], PLAN)
        C = np.zeros((N, N))
        C[0, 0] = DC
        for (u, v, b, step), sym in zip(PLAN, syms):
            levels = 1 << b
            C[u, v] = (sym - (levels - 1) / 2.0) * step   # centered lattice
        img = idctn(C, norm="ortho")
        chans.append(np.clip(np.round(img), 0, 255))
    rgb = np.stack(chans, axis=-1).astype("uint8")
    return Image.fromarray(rgb, "RGB")


def decode_field(img: Image.Image) -> bytes:
    """Recover the bytes encoded by :func:`encode_field`."""
    arr = np.asarray(img.convert("RGB"), dtype=float)
    per_ch = _BITS_PER_CHANNEL
    bits = np.zeros(TOTAL_BITS, dtype=np.uint8)
    pos = 0
    for ch in range(3):
        C = dctn(arr[:, :, ch], norm="ortho")
        for (u, v, b, step) in PLAN:
            levels = 1 << b
            sym = int(round(C[u, v] / step + (levels - 1) / 2.0))
            sym = max(0, min(levels - 1, sym))
            for k in range(b - 1, -1, -1):
                bits[pos] = (sym >> k) & 1; pos += 1
    recovered = np.packbits(bits) ^ _KEYSTREAM
    length = int.from_bytes(recovered[:2].tobytes(), "big")
    return recovered[2:2 + length].tobytes()
