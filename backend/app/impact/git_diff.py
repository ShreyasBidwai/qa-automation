"""A thin git-diff helper: two SHAs → a ChangeSet (T8.1).

Optional seam over the same read-only command runner the GitProvider uses
(``git diff --name-only base..head``): produces the changed file paths the
ImpactSelector consumes. The selector takes a ChangeSet directly — this just
builds one when you have a checked-out repo and two commits. READ-ONLY: only
``git diff`` is ever run; no write path (Standards §18).
"""

from __future__ import annotations

from app.ingestion.commands import CommandRunner, check_output, run_subprocess

from .selector import ChangeSet


def changed_paths(
    repo_path: str,
    base_sha: str,
    head_sha: str,
    *,
    runner: CommandRunner = run_subprocess,
    git_path: str = "git",
    timeout: float = 120.0,
) -> ChangeSet:
    """The files that differ between two commits, as a ChangeSet (deterministic)."""
    result = runner(
        [git_path, "-C", repo_path, "diff", "--name-only", f"{base_sha}..{head_sha}"],
        None,
        timeout,
    )
    return ChangeSet.of(check_output(result, what="git diff").splitlines())
