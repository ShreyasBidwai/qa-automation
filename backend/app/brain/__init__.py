"""The Brain — system-model search over model_nodes/model_edges (Arch §7, TRD §7).

This package holds Brain query services. ``BrainSearch`` is the core semantic
vector search (T2.3); the richer ``BrainResolver`` (codebase fallback + ranking,
graph expansion) lands in T2.4.
"""

from __future__ import annotations

from .cross_layer import (
    CallMatch,
    CrossLayerError,
    CrossLayerResolver,
    EndpointIndex,
    Impact,
    NodeNotFoundError,
    Subgraph,
    record_observed_call,
)
from .resolver import BrainResolver, Resolution, ResolvedNode
from .search import BrainSearch

__all__ = [
    "BrainSearch",
    "BrainResolver",
    "Resolution",
    "ResolvedNode",
    "CallMatch",
    "CrossLayerError",
    "CrossLayerResolver",
    "EndpointIndex",
    "Impact",
    "NodeNotFoundError",
    "Subgraph",
    "record_observed_call",
]
