"""Process-wide runtime state shared by the lifespan, the server's signal
handler, and the readiness endpoint.

Kept as a module-level singleton so the signal handler (which flips readiness on
SIGTERM, before the drain) and the ASGI app reference the same object.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AppState:
    is_ready: bool = False
    is_draining: bool = False


app_state = AppState()
