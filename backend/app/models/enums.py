"""Domain enums (values are the contract strings from TRD §3).

Member names use valid identifiers; the wire/DB values are the hyphenated
strings in the TRD. ``pg_enum`` (see base.py) persists the *values*, so the
Postgres enum types match the TRD exactly.
"""

from __future__ import annotations

import enum


class TestType(str, enum.Enum):
    SMOKE = "smoke"
    HAPPY = "happy"
    NEGATIVE = "negative"
    EDGE = "edge"
    E2E = "e2e"
    JOURNEY = "journey"
    PROFILE = "profile"


class TestLayer(str, enum.Enum):
    API = "api"
    UI = "ui"
    INTEGRATION = "integration"


class OracleSource(str, enum.Enum):
    RULE_DERIVED = "rule-derived"
    CHARACTERIZATION = "characterization"
    SPEC_GROUNDED = "spec-grounded"


class AuthoredBy(str, enum.Enum):
    AI = "ai"
    HUMAN = "human"


class Framework(str, enum.Enum):
    PEST = "pest"
    PYTEST = "pytest"
    PLAYWRIGHT = "playwright"


class RunTrigger(str, enum.Enum):
    MANUAL = "manual"
    CI = "ci"
    CHANGE_IMPACT = "change-impact"


class RunMode(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"


class Outcome(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


class Triage(str, enum.Enum):
    REAL_BUG = "real-bug"
    BAD_TEST = "bad-test"
    FLAKY = "flaky"
    INFRA = "infra"
    UNKNOWN = "unknown"
