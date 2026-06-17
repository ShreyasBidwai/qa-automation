"""Stack-specific ingestion adapters (Arch §2, TRD §5).

The Laravel adapter is the first implementation. For now it extracts a single
endpoint's normalized `EndpointSpec` deterministically (no AI); Sprint 2
generalizes it to a whole-app `NormalizedModel`.
"""

from __future__ import annotations

from .errors import (
    ActionResolutionError,
    CommandFailed,
    CommandTimeout,
    ExtractionError,
    IngestionCommandError,
    RouteNotFound,
    ValidationExtractionError,
)
from .models import (
    EndpointSpec,
    FieldConstraints,
    RelationalRule,
    ValidationField,
)

__all__ = [
    "EndpointSpec",
    "ValidationField",
    "FieldConstraints",
    "RelationalRule",
    "ExtractionError",
    "RouteNotFound",
    "ActionResolutionError",
    "ValidationExtractionError",
    "IngestionCommandError",
    "CommandFailed",
    "CommandTimeout",
]
