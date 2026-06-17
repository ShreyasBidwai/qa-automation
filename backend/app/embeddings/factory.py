"""Config-driven embedding provider selection (mirrors build_ai_provider).

dev/prod use the local fastembed model; tests use the deterministic stub.
"""

from __future__ import annotations

from app.core.config import Settings

from .fastembed_provider import LocalEmbeddingProvider
from .stub import StubEmbeddingProvider
from .types import EmbeddingProvider


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    mode = settings.embedding_provider
    if mode == "stub":
        return StubEmbeddingProvider(dimension=settings.embedding_dim)
    if mode == "local":
        return LocalEmbeddingProvider(
            model=settings.embedding_model, dimension=settings.embedding_dim
        )
    raise ValueError(
        f"unknown embedding_provider {mode!r} (expected 'local' or 'stub')"
    )
