"""Demo-only seed data (NOT production, NOT the AAHOA path).

A clearly-isolated, idempotent fixture that populates a single demo organization so
the full UI can be reviewed with believable data before the first real run. Run it
explicitly with ``python -m app.seed`` (or ``make seed-demo``); it is never invoked
by normal startup, so a clean AAHOA database is just ``make up`` with no seed.
"""

from .demo import DEMO_LOGIN_EMAIL, DEMO_LOGIN_PASSWORD, DEMO_ORG_ID, seed_demo

__all__ = [
    "DEMO_LOGIN_EMAIL",
    "DEMO_LOGIN_PASSWORD",
    "DEMO_ORG_ID",
    "seed_demo",
]
