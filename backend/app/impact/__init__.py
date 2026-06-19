"""Change-impact test selection (Mode B / CI — PRD FR-8, ADR-0024).

Select only the tests a code change could affect: ChangeSet → seed nodes → 1-hop
blast radius via the Brain → covering cases, honest about unmapped changes (widen
on uncertainty).
"""

from __future__ import annotations

from .git_diff import changed_paths
from .selector import (
    CaseSelection,
    ChangeSet,
    ImpactResolver,
    ImpactSelection,
    ImpactSelector,
    node_source_file,
)

__all__ = [
    "CaseSelection",
    "ChangeSet",
    "ImpactResolver",
    "ImpactSelection",
    "ImpactSelector",
    "changed_paths",
    "node_source_file",
]
