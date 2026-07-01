"""Provider-agnostic triage helpers: render the failure, parse the model's label.

Both AI providers assemble the same triage prompt (``TRIAGE_INSTRUCTION`` + the
rendered failure) and map the model's reply to a :class:`Triage` label the same
way, so the two backends stay interchangeable and the parsing is tested once here.

Parsing is deliberately tolerant: a well-behaved model answers with a bare label,
but a chatty one ("This looks like a real-bug because…") is still classified by the
first label it names; anything unrecognisable falls back to ``unknown`` rather than
raising — triage must never break a run.
"""

from __future__ import annotations

import re

from app.models.enums import Triage

from .types import FailureEvidence

# The message can be a whole stack trace; cap it so a giant trace can't dominate the
# (small, cheap) triage prompt. build_within_budget still trims further if needed.
_MESSAGE_CHARS = 4000


def render_failure(failure: FailureEvidence) -> str:
    """Deterministic text form of the evidence for the triage prompt."""
    message = (failure.message or "").strip() or "(no failure message captured)"
    if len(message) > _MESSAGE_CHARS:
        message = message[:_MESSAGE_CHARS] + "\n…(truncated)"
    return (
        f"outcome: {failure.outcome}\n"
        f"test_case_id: {failure.test_case_id}\n"
        "failure message / assertion output:\n"
        f"{message}"
    )


def parse_triage_label(text: str) -> Triage:
    """Map a model reply to a :class:`Triage` label; ``unknown`` if unrecognised.

    Normalises whitespace/underscores to hyphens so ``REAL_BUG`` / ``real bug`` /
    ``real-bug`` all match, accepts a bare label exactly, and otherwise takes the
    first label mentioned anywhere in a prose reply.
    """
    norm = re.sub(r"[\s_]+", "-", text.strip().lower())
    for label in Triage:  # a bare, exact label reply is the common (cheap) case
        if norm == label.value:
            return label
    best: Triage | None = None
    best_at = len(norm) + 1
    for label in Triage:
        at = norm.find(label.value)
        if at != -1 and at < best_at:
            best_at, best = at, label
    return best or Triage.UNKNOWN
