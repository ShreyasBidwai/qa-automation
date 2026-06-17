"""Laravel ingestion (deterministic, AI-free)."""

from __future__ import annotations

from .extractor import LaravelExtractor
from .route_list import RouteFacts, RouteTarget

__all__ = ["LaravelExtractor", "RouteTarget", "RouteFacts"]
