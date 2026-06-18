"""Pluggable embedding layer for the Brain (Architecture §7, TRD §7).

A provider-agnostic ``EmbeddingProvider`` (mirrors ``AIProvider``): local
fastembed for dev/prod, a deterministic stub for tests, selected by config.
Includes the deterministic node-document builder used for retrieval.
"""

from __future__ import annotations

from .document import build_node_document, content_sha
from .errors import EmbeddingDimMismatch, EmbeddingError, EmbeddingProviderError
from .factory import build_embedding_provider
from .stub import StubEmbeddingProvider
from .types import EmbeddingProvider, Vector

__all__ = [
    "EmbeddingProvider",
    "Vector",
    "StubEmbeddingProvider",
    "build_embedding_provider",
    "build_node_document",
    "content_sha",
    "EmbeddingError",
    "EmbeddingProviderError",
    "EmbeddingDimMismatch",
]
