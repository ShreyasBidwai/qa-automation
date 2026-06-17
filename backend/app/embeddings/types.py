"""Provider-agnostic embedding interface (mirrors AIProvider, TRD §5–6).

A single interface with a local fastembed (ONNX, no torch) implementation for
dev/prod and a deterministic stub for tests. Callers (ingest, search) depend on
this Protocol, never a concrete backend.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# A dense embedding vector. The dimension is provider/config-driven and must
# match the model_nodes.embedding column dimension.
Vector = list[float]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """The contract every embedding provider satisfies (provider-agnostic)."""

    dimension: int

    def embed(self, texts: list[str]) -> list[Vector]: ...
