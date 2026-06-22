"""Per-project DB-state-testing tier (B10, ADR-0043).

Opt-in and tiered. ``off`` is the default — no DB-state testing happens at all.
``read_only`` permits SELECT-only table-state assertions (no writes to the
disposable DB beyond a test's own rolled-back transaction). ``full`` permits writes
to the disposable DB and so REQUIRES the non-prod safety gate
(``gate.ensure_disposable``) to pass at execution time.

Persisted as a validated string on ``projects.db_state_tier`` (no pg enum — like
other tier-shaped fields in this codebase); the API validates against this set.
"""

from __future__ import annotations

import enum


class DbStateTier(str, enum.Enum):
    OFF = "off"
    READ_ONLY = "read_only"
    FULL = "full"

    @property
    def allows_read(self) -> bool:
        """Read-only and full may run SELECT table-state assertions; off may not."""
        return self is not DbStateTier.OFF

    @property
    def allows_write(self) -> bool:
        """Only full may write to the disposable DB (and only past the safety gate)."""
        return self is DbStateTier.FULL


# The default for every project: DB-state testing is OFF until explicitly opted in.
DEFAULT_TIER = DbStateTier.OFF
