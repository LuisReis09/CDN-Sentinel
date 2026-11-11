"""Experimental Tardos-style binary codebook and scoring simulator.

This module does not authorize attribution.  A deployment must calibrate
thresholds against its actual media extractor and collusion population.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TardosCodebook:
    users: tuple[str, ...]
    biases: np.ndarray
    bits: np.ndarray
    seed: int

    @classmethod
    def generate(cls, users: list[str], length: int, seed: int = 2026, cutoff: float = 0.01) -> "TardosCodebook":
        if len(users) < 2 or length < 32 or len(set(users)) != len(users):
            raise ValueError("código requer ao menos dois usuários distintos e 32 posições")
        if not 0 < cutoff < 0.5:
            raise ValueError("cutoff inválido")
        rng = np.random.default_rng(seed)
        biases = np.clip(rng.beta(0.5, 0.5, size=length), cutoff, 1 - cutoff)
        bits = (rng.random((len(users), length)) < biases).astype(np.uint8)
        return cls(tuple(users), biases, bits, seed)

    def coalition_copy(self, colluders: list[str], strategy: str = "majority", seed: int = 2026) -> np.ndarray:
        indices = [self.users.index(user) for user in colluders]
        if not indices:
            raise ValueError("colusão vazia")
        choices = self.bits[indices]
        if strategy == "majority":
            count = choices.sum(axis=0)
            return (count * 2 >= len(indices)).astype(np.uint8)
        if strategy == "interleaving":
            rng = np.random.default_rng(seed)
            selected = rng.integers(0, len(indices), size=len(self.biases))
            return choices[selected, np.arange(len(self.biases))]
        raise ValueError("estratégia desconhecida")

    def scores(self, observed: np.ndarray) -> dict[str, float]:
        if observed.shape != self.biases.shape or np.any((observed != 0) & (observed != 1)):
            raise ValueError("sequência observada inválida")
        p = self.biases
        positive = np.sqrt((1 - p) / p)
        negative = np.sqrt(p / (1 - p))
        score = np.where(
            observed[None, :] == 1,
            np.where(self.bits == 1, positive, -negative),
            np.where(self.bits == 0, negative, -positive),
        ).sum(axis=1) / np.sqrt(len(p))
        return {user: float(value) for user, value in zip(self.users, score)}


def simulate(users: int = 100, length: int = 512, colluders: int = 2, seed: int = 2026) -> dict:
    if colluders < 1 or colluders >= users:
        raise ValueError("coalizão inválida")
    codebook = TardosCodebook.generate([f"u{i:04d}" for i in range(users)], length, seed)
    coalition = list(codebook.users[:colluders])
    observed = codebook.coalition_copy(coalition)
    scores = codebook.scores(observed)
    innocent_scores = [value for user, value in scores.items() if user not in coalition]
    return {
        "users": users, "length": length, "colluders": coalition, "seed": seed,
        "coalition_scores": {user: scores[user] for user in coalition},
        "max_innocent_score": max(innocent_scores),
        "status": "SIMULATION_ONLY", "attribution": "NONE",
    }
