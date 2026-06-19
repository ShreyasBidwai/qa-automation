"""Mutation-kill gate for E2E plans (Standards §12) — CI-enforced.

The backend's thesis: an assertion that no mutation could make fail is worthless.
For E2E, the static gate rejects *tautological* assertions before a spec is even
rendered — e.g. merely "the page loaded", or an assertion with no concrete
target. (The runtime half — proving a real assertion actually fails on a seeded
bug — is the heavy ``e2e_runner`` lane, mirroring the backend mutant-kill test.)

Pure + deterministic; runs at generation time so a tautological oracle can never
be persisted.
"""

from __future__ import annotations

from .e2e_plan import E2EAssertion, PlannedE2ECase
from .errors import MutationGateError

# Assertion kinds that assert nothing a mutation could kill.
_TAUTOLOGICAL_KINDS = frozenset({"loaded", "page_loaded", "noop", "smoke", "exists"})


def is_tautological(assertion: E2EAssertion) -> bool:
    """True if the assertion has no real check (a no-op / empty target)."""
    return assertion.kind in _TAUTOLOGICAL_KINDS or not assertion.target.strip()


def enforce_mutation_gate(plan: list[PlannedE2ECase]) -> None:
    """Raise ``MutationGateError`` if any case has a tautological / missing oracle.

    Every case must carry at least one assertion, and none may be tautological —
    otherwise the generated test could pass without checking anything real.
    """
    offenders: list[str] = []
    for case in plan:
        if not case.assertions:
            offenders.append(f"{case.name}: no assertions")
            continue
        for assertion in case.assertions:
            if is_tautological(assertion):
                offenders.append(
                    f"{case.name}: tautological assertion "
                    f"{assertion.kind!r} target={assertion.target!r}"
                )
    if offenders:
        raise MutationGateError(
            "mutation-kill gate rejected tautological assertions: "
            + "; ".join(offenders)
        )
