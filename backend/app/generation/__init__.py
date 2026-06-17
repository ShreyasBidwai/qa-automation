"""Test generation: deterministic plan (no AI) + AI-rendered Pest scripts.

Two strictly separate phases (this package keeps them apart):
- PHASE 1 (plan.py): derive cases + payloads + expected statuses in pure Python.
- PHASE 2 (render.py): the AIProvider assembles the test code AROUND the
  deterministically-computed payload/status — it never invents them.

Oracle honesty is mandatory: rule/auth-derived negatives are "rule-derived";
the happy case is "characterization" (status + structural shape only). Nothing
is "spec-grounded" — no requirements are ingested yet.
"""

from __future__ import annotations

from .errors import GenerationError
from .generator import GeneratedCase, TestGenerator
from .plan import DbDependency, ExpectedOutcome, PlannedCase, plan_cases

__all__ = [
    "TestGenerator",
    "GeneratedCase",
    "plan_cases",
    "PlannedCase",
    "ExpectedOutcome",
    "DbDependency",
    "GenerationError",
]
