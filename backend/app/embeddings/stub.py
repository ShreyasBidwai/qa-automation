"""Deterministic fake EmbeddingProvider for tests (Standards §15).

Produces unit pseudo-vectors seeded from a hash of the text — NO model download,
no network. Identical text yields an identical vector (cosine distance 0), so
search ranks an exact node-document match first; different texts get stable,
distinct vectors. Same input always yields the same output.
"""

from __future__ import annotations

import hashlib
import math

from .types import Vector


class StubEmbeddingProvider:
    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[Vector]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> Vector:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimension:
            digest = hashlib.sha256(f"{text}#{counter}".encode()).digest()
            for offset in range(0, len(digest), 4):
                if len(values) >= self.dimension:
                    break
                raw = int.from_bytes(digest[offset : offset + 4], "big")
                values.append(raw / 2**32 - 0.5)  # centre in [-0.5, 0.5)
            counter += 1
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]  # unit length → cosine = dot product
