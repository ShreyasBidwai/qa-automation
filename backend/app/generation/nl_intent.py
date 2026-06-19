"""Mode C, step 1 — natural language → a structured TestIntent (T5 core).

The ONLY non-deterministic edge in Mode C: an AIProvider turns free-text ("test
the checkout flow") into a rough intent. Everything after is deterministic. The
AI output is then passed through deterministic post-processing/validation:
keywords are normalised (lower-cased, de-stop-worded, de-duplicated) and the
scenario type is validated against a closed enum. If the model returns nothing
usable, we fall back to extracting the intent straight from the NL — so a weak or
canned provider (the test stub) still yields a valid, deterministic intent.

Lives in a new ``nl_*`` file per the Sprint-5 coordination contract; reuses the
shared AIProvider contract without modifying it.
"""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass

from app.ai.types import AIProvider, Subgraph

from .errors import GenerationError


class IntentError(GenerationError):
    """The NL could not be turned into a usable TestIntent (e.g. empty input)."""


class ScenarioType(str, enum.Enum):
    HAPPY_PATH = "happy_path"
    NEGATIVE = "negative"
    JOURNEY = "journey"
    SMOKE = "smoke"


@dataclass(frozen=True)
class TestIntent:
    raw_nl: str
    keywords: tuple[str, ...]
    scenario_type: ScenarioType


_INSTRUCTION = (
    "You turn a QA engineer's free-text request into a small JSON object "
    '{"keywords": [...], "scenario_type": "happy_path|negative|journey|smoke"}. '
    "keywords are the app areas/nouns to test; scenario_type is the kind of test. "
    "Reply with ONLY the JSON."
)

# Dropped from keyword extraction — generic verbs/articles with no target value.
_STOPWORDS = frozenset(
    {
        "test",
        "tests",
        "testing",
        "the",
        "a",
        "an",
        "that",
        "for",
        "to",
        "of",
        "and",
        "or",
        "please",
        "check",
        "verify",
        "when",
        "with",
        "this",
        "should",
        "make",
        "sure",
        "case",
        "cases",
        "scenario",
        "flow",
    }
)
_TOKEN = re.compile(r"[a-z0-9]+")

# Keyword hints → scenario type (deterministic, priority top-to-bottom).
_NEGATIVE_HINTS = frozenset(
    {
        "invalid",
        "missing",
        "wrong",
        "empty",
        "fail",
        "failure",
        "error",
        "errors",
        "unauthorized",
        "forbidden",
        "negative",
        "reject",
        "rejected",
    }
)
_JOURNEY_HINTS = frozenset(
    {"flow", "journey", "checkout", "end", "e2e", "through", "across", "onboarding"}
)
_SMOKE_HINTS = frozenset({"smoke", "loads", "load", "renders", "render", "available"})


def _context(nl: str) -> Subgraph:
    return Subgraph(snippets=[json.dumps({"request": nl})])


def _extract_json(raw: str) -> dict[str, object] | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _normalize_keywords(ai_keywords: object, nl: str) -> tuple[str, ...]:
    """Normalised keywords from the AI output, falling back to the NL itself."""
    raw: list[str] = []
    if isinstance(ai_keywords, list):
        for item in ai_keywords:
            raw.extend(_tokens(str(item)))
    if not raw:  # weak/absent AI output → extract straight from the request
        raw = _tokens(nl)

    seen: set[str] = set()
    keywords: list[str] = []
    for token in raw:
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return tuple(keywords)


def _classify_scenario(
    ai_scenario: object, nl: str, keywords: tuple[str, ...]
) -> ScenarioType:
    if isinstance(ai_scenario, str):
        try:
            return ScenarioType(ai_scenario.strip().lower())
        except ValueError:
            pass  # not a valid tier — fall through to deterministic inference
    hints = set(_tokens(nl)) | set(keywords)
    if hints & _NEGATIVE_HINTS:
        return ScenarioType.NEGATIVE
    if hints & _JOURNEY_HINTS:
        return ScenarioType.JOURNEY
    if hints & _SMOKE_HINTS:
        return ScenarioType.SMOKE
    return ScenarioType.HAPPY_PATH


def parse_test_intent(
    provider: AIProvider, nl: str, *, budget_tokens: int = 512
) -> TestIntent:
    """NL → TestIntent: AIProvider proposes, deterministic post-processing decides."""
    if not nl.strip():
        raise IntentError("empty natural-language request")

    raw = provider.generate(_INSTRUCTION, _context(nl), budget_tokens)
    parsed = _extract_json(raw)
    keywords = _normalize_keywords(parsed.get("keywords") if parsed else None, nl)
    if not keywords:
        raise IntentError(f"no testable keywords in request: {nl!r}")
    scenario = _classify_scenario(
        parsed.get("scenario_type") if parsed else None, nl, keywords
    )
    return TestIntent(raw_nl=nl, keywords=keywords, scenario_type=scenario)
