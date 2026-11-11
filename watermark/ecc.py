"""Small dependency-free Reed-Solomon codec for forensic bit payloads.

This is used for experiments and payload framing, not as an attribution
oracle.  Interleaving is exposed separately so burst errors can be spread
before decoding.
"""

from __future__ import annotations

from dataclasses import dataclass


def _mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
    return result & 0xFF


def _pow(a: int, n: int) -> int:
    result = 1
    for _ in range(n):
        result = _mul(result, a)
    return result


def _poly_mul(left: list[int], right: list[int]) -> list[int]:
    result = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] ^= _mul(a, b)
    return result


def _generator(parity: int) -> list[int]:
    result = [1]
    for i in range(parity):
        result = _poly_mul(result, [1, _pow(2, i)])
    return result


@dataclass(frozen=True)
class ReedSolomonCodec:
    parity_symbols: int = 16

    def __post_init__(self) -> None:
        if not 2 <= self.parity_symbols <= 64 or self.parity_symbols % 2:
            raise ValueError("parity_symbols deve ser par e estar entre 2 e 64")

    def encode(self, data: bytes) -> bytes:
        generator = _generator(self.parity_symbols)
        message = list(data) + [0] * self.parity_symbols
        for i in range(len(data)):
            factor = message[i]
            if factor:
                for j, coefficient in enumerate(generator):
                    message[i + j] ^= _mul(coefficient, factor)
        return data + bytes(message[-self.parity_symbols:])

    def syndromes(self, codeword: bytes) -> list[int]:
        return [self._eval(list(codeword), _pow(2, i)) for i in range(self.parity_symbols)]

    @staticmethod
    def _eval(poly: list[int], x: int) -> int:
        value = 0
        for coefficient in poly:
            value = _mul(value, x) ^ coefficient
        return value

    def verify(self, codeword: bytes) -> bool:
        return not any(self.syndromes(codeword))

    def decode(self, codeword: bytes) -> tuple[bytes, int]:
        """Decode no-error and erasure-free codewords.

        Full Berlekamp–Massey/Chien correction is intentionally not hidden
        behind a fake result: for now this method verifies a codeword and
        reports failure when correction would be required.  The benchmark
        records this as a decoding failure, while repetition/soft evidence in
        the visual adapters remains available for real noisy media.
        """
        if len(codeword) <= self.parity_symbols:
            raise ValueError("codeword curto")
        if not self.verify(codeword):
            raise ValueError("Reed-Solomon detectou erros que exigem correção")
        return codeword[:-self.parity_symbols], 0


def interleave(data: bytes, lanes: int) -> bytes:
    if lanes <= 0:
        raise ValueError("lanes deve ser positivo")
    buckets = [bytearray() for _ in range(min(lanes, max(1, len(data))))]
    for index, value in enumerate(data):
        buckets[index % len(buckets)].append(value)
    return b"".join(bytes(bucket) for bucket in buckets)


def deinterleave(data: bytes, lanes: int) -> bytes:
    if lanes <= 0:
        raise ValueError("lanes deve ser positivo")
    lane_count = min(lanes, max(1, len(data)))
    lengths = [len(data) // lane_count + (1 if i < len(data) % lane_count else 0) for i in range(lane_count)]
    buckets = []
    offset = 0
    for length in lengths:
        buckets.append(data[offset:offset + length])
        offset += length
    output = bytearray()
    for index in range(max(lengths, default=0)):
        for bucket in buckets:
            if index < len(bucket):
                output.append(bucket[index])
    return bytes(output)
