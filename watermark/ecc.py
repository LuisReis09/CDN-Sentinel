"""Small dependency-free Reed-Solomon codec for forensic bit payloads.

This is used for experiments and payload framing, not as an attribution
oracle.  Interleaving is exposed separately so burst errors can be spread
before decoding.
"""

from __future__ import annotations

from dataclasses import dataclass


class Secded55Codec:
    """Extended Hamming (55, 48): correct one bit, detect two bits.

    Positions are one-based. Six Hamming parity positions cover 54 bits and
    position 55 is the overall parity bit. This adds seven bits to the 48-bit
    visual marker without changing its ledger collision bound.
    """

    data_bits = 48
    code_bits = 55
    parity_positions = (1, 2, 4, 8, 16, 32)

    def encode(self, bits: list[int]) -> list[int]:
        if len(bits) != self.data_bits or any(bit not in (0, 1) for bit in bits):
            raise ValueError("SECDED55 requires exactly 48 bits")
        code = [0] * (self.code_bits + 1)
        positions = [position for position in range(1, 55) if position not in self.parity_positions]
        for position, bit in zip(positions, bits):
            code[position] = bit
        for parity_position in self.parity_positions:
            code[parity_position] = sum(code[position] for position in range(1, 55) if position & parity_position) & 1
        code[55] = sum(code[1:55]) & 1
        return code[1:]

    def decode(self, bits: list[int]) -> tuple[list[int] | None, int, str]:
        if len(bits) != self.code_bits or any(bit not in (0, 1) for bit in bits):
            raise ValueError("SECDED55 requires exactly 55 bits")
        code = [0] + list(bits)
        syndrome = sum(
            parity_position
            for parity_position in self.parity_positions
            if sum(code[position] for position in range(1, 55) if position & parity_position) & 1
        )
        overall = sum(code[1:]) & 1
        corrected = 0
        if syndrome and overall:
            if syndrome > 54:
                return None, 0, "UNCORRECTABLE"
            code[syndrome] ^= 1
            corrected = 1
        elif syndrome and not overall:
            return None, 0, "UNCORRECTABLE"
        elif overall:
            code[55] ^= 1
            corrected = 1
        positions = [position for position in range(1, 55) if position not in self.parity_positions]
        data = [code[position] for position in positions]
        if self.encode(data) != code[1:]:
            return None, 0, "UNCORRECTABLE"
        return data, corrected, "CORRECTED" if corrected else "CLEAN"


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
