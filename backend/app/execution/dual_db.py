"""Dual-DB safety guard (Architecture §9, Standards §11).

Execution targets ONLY the writable, ephemeral test DB. These helpers refuse any
other connection up front, so a misconfigured target can never reach a live
``pest`` — execution never writes to a read-only/real database.
"""

from __future__ import annotations

from .errors import ReadOnlyTargetError
from .types import DbHandle, DbRole, TargetEnv


def ensure_safe_target(env: TargetEnv) -> None:
    """Raise unless the execution DB is the writable, ephemeral test DB."""
    db = env.execution_db
    if db.role is not DbRole.WRITABLE_TEST:
        raise ReadOnlyTargetError(
            "execution target must be the writable test DB, "
            f"got role={db.role.value}"
        )
    if not db.ephemeral:
        raise ReadOnlyTargetError("execution target DB must be ephemeral (throwaway)")
    if env.introspection_db is not None and (
        env.introspection_db.role is not DbRole.READ_ONLY_REAL
    ):
        raise ReadOnlyTargetError("introspection DB must be read-only")


def subprocess_db_env(handle: DbHandle) -> dict[str, str]:
    """Env overlay that points the target app at the test DB and ONLY that DB.

    Any inherited ``DATABASE_URL`` is blanked so Laravel cannot prefer a real
    connection string over the explicit sqlite test settings.
    """
    if handle.role is not DbRole.WRITABLE_TEST:
        raise ReadOnlyTargetError("refusing to build env for a non-test DB")
    if not handle.url.startswith("sqlite:"):
        # Only the ephemeral sqlite test DB is supported this sprint; never fall
        # back to a real driver.
        raise ReadOnlyTargetError(f"unsupported execution DB url: {handle.url!r}")

    database = handle.url[len("sqlite:") :]
    if database.startswith("//"):  # sqlite:///abs/path -> /abs/path
        database = database[2:]
    if not database:
        database = ":memory:"
    return {
        "DB_CONNECTION": "sqlite",
        "DB_DATABASE": database,
        "DATABASE_URL": "",
    }
