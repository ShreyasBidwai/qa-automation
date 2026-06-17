"""Read-only git provider contract (Architecture §4 — INGESTION reads git).

A provider checks out a ref to a local working tree and resolves its commit SHA.
READ-ONLY by design: there is no push/write method, ever — the platform only
reads target code, it never modifies the remote.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CheckoutHandle:
    """A checked-out working tree: where it is, and exactly what commit it is."""

    path: str  # local working-tree directory
    sha: str  # resolved HEAD commit SHA
    ref: str  # the ref that was requested


@runtime_checkable
class GitProvider(Protocol):
    def checkout(self, repo_url: str, ref: str) -> CheckoutHandle: ...

    def cleanup(self, handle: CheckoutHandle) -> None: ...
