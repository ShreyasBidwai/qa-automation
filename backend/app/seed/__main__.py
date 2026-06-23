"""``python -m app.seed`` — load the isolated demo dataset (idempotent).

NOT part of startup. A reviewer runs this once (``make seed-demo``) against an
already-running stack to populate every screen; a clean AAHOA database is ``make
up`` with no seed. Re-running clears and rebuilds the demo org, never duplicating.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.core.db import connect_with_retries, create_engine, create_sessionmaker
from app.core.logging import configure_logging

from .demo import DEMO_LOGIN_EMAIL, DEMO_LOGIN_PASSWORD, seed_demo

logger = logging.getLogger("app.seed")


async def _main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    await connect_with_retries(engine, settings)
    try:
        async with sessionmaker() as session:
            await seed_demo(session)
    finally:
        await engine.dispose()
    logger.info(
        "seed.demo.completed",
        extra={"login_email": DEMO_LOGIN_EMAIL, "login_password": DEMO_LOGIN_PASSWORD},
    )


if __name__ == "__main__":
    configure_logging("INFO")
    asyncio.run(_main())
