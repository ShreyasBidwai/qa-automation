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


class FindingLayer(str, enum.Enum):
    """Which layer a Finding manifests at (reporting, T7.1).

    Distinct from ``TestLayer`` (how a case runs): a finding is located on the
    stack. ``db`` is reserved for DB-level findings surfaced by later work.
    """

    UI = "ui"
    API = "api"
    DB = "db"


class OracleSource(str, enum.Enum):
    RULE_DERIVED = "rule-derived"
    CHARACTERIZATION = "characterization"
    SPEC_GROUNDED = "spec-grounded"


class AuthoredBy(str, enum.Enum):
    AI = "ai"
    HUMAN = "human"


class CaseOrigin(str, enum.Enum):
    """How a particular test-case *version* came to exist (per-version provenance).

    Distinct from ``AuthoredBy`` (who originally authored the logical case):
    ``origin`` records the act that produced *this row*. A re-generation sibling
    or other origins may be added later (forward-only, additive).
    """

    GENERATED = "generated"
    EDITED = "edited"
    # A re-generation against a human-edited case: a non-current candidate the
    # human can later accept/reject (resolution is T3.3). See [[CaseMergeService]].
    PROPOSED = "proposed"
    # A case a human wrote from scratch (Mode A) — not AI-generated and not an
    # edit of a prior version. Starts a fresh lineage at version 1, current, and
    # is ``edited_by_human=true`` so re-generation can only ever propose against
    # it (never clobber). See [[CaseAuthoringService]].
    AUTHORED = "authored"


class ProposalStatus(str, enum.Enum):
    """Lifecycle of a re-generation proposal against a human-edited case.

    Null on non-proposal versions; set to ``pending`` when a proposal is created
    by the merge engine. ``accepted``/``rejected`` are written by resolution
    (T3.3) — this sprint only creates pending proposals.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


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


class CoverageDimension(str, enum.Enum):
    ENDPOINT = "endpoint"
    PAGE = "page"
    JOURNEY = "journey"
    ROLE_MATRIX = "role-matrix"


class NodeKind(str, enum.Enum):
    """A system-model ("Brain") node kind (TRD §3, §7)."""

    ENDPOINT = "endpoint"
    PAGE = "page"
    MODEL = "model"
    TABLE = "table"
    ROLE = "role"


class EdgeKind(str, enum.Enum):
    """A directed relationship between two model nodes (TRD §3, §7)."""

    CALLS = "calls"
    IMPLEMENTS = "implements"
    READS = "reads"
    WRITES = "writes"
    COVERS = "covers"
    OBSERVED_IN = "observed_in"
    DERIVED_FROM = "derived_from"
    # A page links/navigates to another page (observed in the rendered DOM by the
    # runtime frontend crawler, T4.2). Distinct from ``calls`` (page → backend
    # endpoint). See [[FrontendCrawler]].
    NAVIGATES = "navigates"


class AuthVariant(str, enum.Enum):
    """Which AuthStrategy logs a session in against a live target (T4.2a).

    Config-only (selects a strategy); not persisted. Only ``none``,
    ``test_bypass`` and ``manual`` are implemented now — the automated variants
    are declared behind the same contract but parked (see docs/parking-lot.md).
    """

    NONE = "none"
    TEST_BYPASS = "test_bypass"
    TOTP = "totp"
    EMAIL_OTP = "email_otp"
    SMS_OTP = "sms_otp"
    MANUAL = "manual"


class AuthChallenge(str, enum.Enum):
    """The login challenge a target presented, recorded in the challenge log.

    Persisted (``auth_challenge`` pg enum). ``2fa`` is a non-OTP second factor
    (e.g. an authenticator approval) distinct from a one-time ``otp`` code.
    """

    NONE = "none"
    OTP = "otp"
    TWO_FA = "2fa"
