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

from .case_key import compute_case_key
from .e2e_generator import E2EGenerator, GeneratedE2ECase
from .e2e_plan import (
    E2EAssertion,
    E2EStep,
    PlannedE2ECase,
    build_e2e_plan,
    e2e_case_key,
)
from .e2e_render import render_e2e_spec
from .errors import E2EPlanError, GenerationError, MutationGateError
from .generator import GeneratedCase, TestGenerator
from .mutation_gate import enforce_mutation_gate, is_tautological
from .plan import DbDependency, ExpectedOutcome, PlannedCase, plan_cases

__all__ = [
    "TestGenerator",
    "GeneratedCase",
    "compute_case_key",
    "plan_cases",
    "PlannedCase",
    "ExpectedOutcome",
    "DbDependency",
    "GenerationError",
    "E2EGenerator",
    "GeneratedE2ECase",
    "E2EAssertion",
    "E2EStep",
    "PlannedE2ECase",
    "build_e2e_plan",
    "e2e_case_key",
    "render_e2e_spec",
    "enforce_mutation_gate",
    "is_tautological",
    "E2EPlanError",
    "MutationGateError",
]
