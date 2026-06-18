"""Deterministic logical-case identity (T3.2).

A test case's ``case_key`` is a stable string derived purely from its plan, so
the same plan yields the same key across runs and re-generation can match "the
same logical case" rather than duplicating it (TRD §3 never-clobber). The key
is the *only* thing that links a fresh generation back to an existing lineage.
"""

from __future__ import annotations

from app.ingestion.models import EndpointSpec

from .plan import PlannedCase


def compute_case_key(spec: EndpointSpec, case: PlannedCase) -> str:
    """``"{METHOD} /{uri}::{case_type}::{name}"`` — e.g.
    ``"POST /api/users::negative::email_required_missing"``.

    Endpoint + case type + the targeted rule/field. ``case.name`` already encodes
    field+rule uniquely within an endpoint (e.g. ``email_required_missing``,
    ``age_size_below`` vs ``age_size_above`` — which share the coarse ``rule``
    ``"size"`` but are distinct cases), so the key never collides for two
    different logical cases of one endpoint. Pure function of its inputs.
    """
    endpoint = f"{spec.method.upper()} /{spec.uri.lstrip('/')}"
    return f"{endpoint}::{case.case_type.value}::{case.name}"
