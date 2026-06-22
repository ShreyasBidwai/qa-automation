"""Cross-layer DB-state testing (B10) — the table end of the blast path.

Deepens testing from "the API response is right" to "the DATABASE landed in the
right state": after a POST creates an order, assert the ``orders`` row exists with
the right columns; after a soft-delete, assert the row is flagged, not gone.

The load-bearing safety rule (the B10 equivalent of B8's "never heal an
assertion"): DB-state testing NEVER runs against a production database. The target
must be EXPLICITLY flagged disposable/non-prod; if that flag is absent or the DB
looks prod, ``gate.ensure_disposable`` REFUSES — structurally, before any write.
"""

from __future__ import annotations

from .errors import (
    DbStateError,
    ProdTargetRefused,
    UnsafeIdentifierError,
    WriteNotPermitted,
)
from .gate import DisposableTarget, ensure_disposable, looks_prod
from .oracle import (
    TablePredicate,
    TableStateCheck,
    TableStateResult,
    classify_oracle,
    evaluate_table_state,
)
from .tiers import DbStateTier

__all__ = [
    "DbStateError",
    "ProdTargetRefused",
    "UnsafeIdentifierError",
    "WriteNotPermitted",
    "DisposableTarget",
    "ensure_disposable",
    "looks_prod",
    "TablePredicate",
    "TableStateCheck",
    "TableStateResult",
    "classify_oracle",
    "evaluate_table_state",
    "DbStateTier",
]
