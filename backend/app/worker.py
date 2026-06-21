"""Runner-worker entrypoint: ``python -m app.worker`` (B5, ADR-0036).

The execution plane. Polls the durable job queue (B4), claims due jobs with
``FOR UPDATE SKIP LOCKED``, and runs each through the composed run/ingest executors
in its OWN environment — writing results/findings back through the DB and marking
the job terminal (reusing B4's claim/cancel/retry). This process carries the
toolchains (in its image); the backend stays toolchain-free and only enqueues.

Run as a separate service from the slim backend (infra/docker-compose.app.yml).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from pydantic import ValidationError

from .core.config import Settings, get_settings
from .core.db import connect_with_retries, create_engine, create_sessionmaker
from .core.logging import configure_logging

logger = logging.getLogger("app.worker")


async def _run(settings: Settings) -> None:
    # Imported after logging is configured so wiring logs through JSON.
    from .api.composition import build_ingestor, build_run_executor
    from .api.jobs import make_handlers
    from .services.job_worker import JobWorker

    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    await connect_with_retries(engine, settings)
    logger.info("worker: database reachable")

    executor = build_run_executor(settings)
    ingestor = build_ingestor(settings)
    handlers = make_handlers(ingestor=ingestor, executor=executor)
    worker = JobWorker(
        sessionmaker,
        handlers,
        worker_id=settings.worker_id,
        backoff_base_seconds=settings.job_backoff_base_seconds,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info(
        "worker: started",
        extra={
            "worker_id": settings.worker_id,
            "executor_mode": settings.executor_mode,
        },
    )
    try:
        await worker.run_forever(
            poll_interval_seconds=settings.job_poll_interval_seconds, stop_event=stop
        )
    finally:
        await engine.dispose()
        logger.info("worker: stopped")


def main() -> None:
    try:
        settings = get_settings()
    except ValidationError as exc:
        configure_logging("INFO")
        logger.critical(
            "invalid configuration; required settings missing or invalid",
            extra={"error_count": exc.error_count()},
        )
        sys.exit(1)

    configure_logging(settings.log_level)
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
