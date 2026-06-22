"""Spectral codec: lossless bytes <-> a smooth 256x256 RGB field.

Payload is carried in the low-frequency 2D-DCT coefficients of each color
channel (not per pixel), so the inverse transform is a smooth gradient and
*every pixel is load-bearing*. Each coefficient carries several bits via a
centered uniform lattice whose level count is allocated by a decaying amplitude
envelope (waterfilling): low frequencies get larger amplitude and more bits.

Robustness comes from lossless PNG: the only channel noise is 8-bit spatial
rounding, which perturbs each coefficient by < ~0.7. Lattice steps are kept
above ``step_min`` so symbols recover exactly (BER 0) as long as the field
stays within [0, 255] (no clipping).

A codec is parameterised by its frequency band: a lower ``freq_r`` yields a
smoother field with less capacity. ``SpectralCodec(freq_r=18)`` is the module
default; the glyph layer uses a smaller band for the ultra-smooth look.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.fft import dctn, idctn

N = 256
FREQ_R = 18          # default band: keep u+v <= FREQ_R
STEP_MIN = 3.2       # min lattice step (must exceed ~2x the 0.7 rounding noise)
BMAX = 7             # cap bits per coefficient
ENV0 = 6000.0        # amplitude envelope scale (std ~21, no clipping)
_HEADER_BITS = 16    # uint16 payload length prefix


class SpectralCodec:
    """Lossless bytes <-> smooth RGB field for a given low-frequency band."""

    def __init__(self, freq_r=FREQ_R, env0=ENV0, step_min=STEP_MIN, bmax=BMAX, n=N):
        self.n = n
        self.dc = 128.0 * n
        self.plan = self._build_plan(freq_r, env0, step_min, bmax)
        self.bits_per_channel = sum(b for _, _, b, _ in self.plan)
        self.total_bits = self.bits_per_channel * 3
        self.capacity_bytes = (self.total_bits - _HEADER_BITS) // 8
        full_bytes = (self.total_bits + 7) // 8
        # Whitening keystream: XORed over payload + padding so the symbol stream
        # is uniform regardless of content -> data-independent energy (no clip
        # bias) and a payload-independent look.
        self.keystream = np.random.default_rng(0x5A17).integers(
            0, 256, full_bytes
        ).astype(np.uint8)

    @staticmethod
    def _build_plan(freq_r, env0, step_min, bmax):
        plan = []
        for u in range(freq_r + 1):
            for v in range(freq_r + 1 - u):
                if (u, v) == (0, 0):
                    continue
                amp = env0 / (1.0 + (u + v))
                bits = min(bmax, int(np.floor(np.log2(max(1.0, 2.0 * amp / step_min)))))
                if bits < 1:
                    continue
                plan.append((u, v, bits, 2.0 * amp / (1 << bits)))
        plan.sort(key=lambda c: (c[0] + c[1], c[0], c[1]))
        return plan

    def encode_to_field(self, payload: bytes) -> np.ndarray:
        """Encode bytes into an unclipped float RGB field (channel mean ~128).

        Lets a caller apply an invertible transform before the single 8-bit
        rounding; pair with :meth:`decode_from_field`.
        """
        if len(payload) > self.capacity_bytes:
            raise ValueError(
                f"payload {len(payload)}B exceeds capacity {self.capacity_bytes}B"
            )
        data = np.frombuffer(
            len(payload).to_bytes(2, "big") + bytes(payload), dtype=np.uint8
        )
        buf = self.keystream.copy()
        buf[: data.size] ^= data
        bits = np.unpackbits(buf)[: self.total_bits]

        per = self.bits_per_channel
        chans = []
        for ch in range(3):
            slice_bits = bits[ch * per:(ch + 1) * per]
            C = np.zeros((self.n, self.n))
            C[0, 0] = self.dc
            pos = 0
            for (u, v, b, step) in self.plan:
                sym = 0
                for _ in range(b):
                    sym = (sym << 1) | int(slice_bits[pos]); pos += 1
                C[u, v] = (sym - ((1 << b) - 1) / 2.0) * step
            chans.append(idctn(C, norm="ortho"))
        return np.stack(chans, axis=-1)

    def decode_from_field(self, field: np.ndarray) -> bytes:
        """Recover bytes from a float RGB field (inverse of encode_to_field)."""
        bits = np.zeros(self.total_bits, dtype=np.uint8)
        pos = 0
        for ch in range(3):
            C = dctn(field[:, :, ch], norm="ortho")
            for (u, v, b, step) in self.plan:
                sym = int(round(C[u, v] / step + ((1 << b) - 1) / 2.0))
                sym = max(0, min((1 << b) - 1, sym))
                for k in range(b - 1, -1, -1):
                    bits[pos] = (sym >> k) & 1; pos += 1
        recovered = np.packbits(bits) ^ self.keystream
        length = int.from_bytes(recovered[:2].tobytes(), "big")
        return recovered[2:2 + length].tobytes()

    def encode(self, payload: bytes) -> Image.Image:
        rgb = np.clip(np.round(self.encode_to_field(payload)), 0, 255).astype("uint8")
        return Image.fromarray(rgb, "RGB")

    def decode(self, img: Image.Image) -> bytes:
        return self.decode_from_field(np.asarray(img.convert("RGB"), dtype=float))


_DEFAULT = SpectralCodec()
PLAN = _DEFAULT.plan
CAPACITY_BYTES = _DEFAULT.capacity_bytes


def encode_field(payload: bytes) -> Image.Image:
    """Encode bytes into a 256x256 RGB field (default band)."""
    return _DEFAULT.encode(payload)


def decode_field(img: Image.Image) -> bytes:
    """Recover the bytes encoded by :func:`encode_field`."""
    return _DEFAULT.decode(img)
