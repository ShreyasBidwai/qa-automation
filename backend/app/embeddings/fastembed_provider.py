"""Local embedding provider via fastembed (ONNX, no torch).

Default model BAAI/bge-small-en-v1.5 (384-dim), config-driven. fastembed is
imported lazily so this module imports cleanly in the fast test image where
fastembed is not installed (only the real-embedding lane installs it).
"""

from __future__ import annotations

from .errors import EmbeddingDimMismatch, EmbeddingProviderError
from .types import Vector


class LocalEmbeddingProvider:
    def __init__(self, *, model: str, dimension: int) -> None:
        self.dimension = dimension
        self._model_name = model
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised only without dep
            raise EmbeddingProviderError(
                "fastembed is not installed; install requirements-embed.txt "
                "(or use the stub provider)"
            ) from exc
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[Vector]:
        try:
            vectors = [
                [float(x) for x in vector] for vector in self._model.embed(texts)
            ]
        except Exception as exc:  # normalize arbitrary backend failures (Std §7)
            raise EmbeddingProviderError(
                f"fastembed failed to embed with {self._model_name!r}"
            ) from exc
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingDimMismatch(
                    f"{self._model_name!r} produced dim {len(vector)}, "
                    f"expected {self.dimension}"
                )
        return vectors
