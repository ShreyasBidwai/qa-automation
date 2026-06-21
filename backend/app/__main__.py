"""Server entrypoint: ``python -m app``.

Owns the uvicorn ``Server`` so SIGTERM/SIGINT can flip readiness off *before*
the drain begins (Standards §11): handle_exit disables readiness and logs, then
delegates to uvicorn, which stops accepting connections, drains in-flight
requests up to the graceful-shutdown timeout, and finally runs lifespan
shutdown (which closes DB connections).
"""

from __future__ import annotations

import logging
import sys
from types import FrameType

import uvicorn
from pydantic import ValidationError

from .core.config import get_settings
from .core.logging import configure_logging
from .core.state import app_state

logger = logging.getLogger("app")


class GracefulServer(uvicorn.Server):
    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if not app_state.is_draining:
            app_state.is_ready = False
            app_state.is_draining = True
            logger.info(
                "received shutdown signal; readiness disabled, draining",
                extra={"signal": int(sig)},
            )
        super().handle_exit(sig, frame)


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

    # Imported after logging is configured so app wiring logs through JSON.
    from .api.composition import build_ingestor, build_run_executor
    from .main import create_app

    app = create_app()
    # Compose the run/ingest ports (stubs by default → zero-cred boot). create_app
    # leaves them None so the fast lane stubs them per-test; the real server wires
    # them here from settings (docs/running.md).
    #
    # Decoupled topology (B5, ADR-0036): in `orchestrator` mode the backend is the
    # toolchain-free control plane — it enqueues and runner workers (python -m
    # app.worker) execute — so it composes NO executor/ingestor and stays slim. In
    # `stub` mode it runs them in-process (single box).
    if settings.executor_mode == "orchestrator":
        logger.info(
            "startup: orchestrator topology — runs dispatched to runner workers"
        )
    else:
        app.state.run_executor = build_run_executor(settings)
        app.state.ingestor = build_ingestor(settings)

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=settings.app_port,
        log_config=None,  # we own logging
        access_log=False,  # we emit our own structured access logs
        timeout_graceful_shutdown=int(settings.shutdown_drain_timeout_seconds),
    )
    GracefulServer(config).run()


if __name__ == "__main__":
    main()
