"""Provider-agnostic AI interface and payload types (TRD §5).

`Subgraph` is the retrieved context payload the Brain hands to the AI layer — a
small set of nodes/edges/snippets rendered deterministically under a hard token
budget (never a repo dump, Arch §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.models.enums import Triage

# Triage labels reuse the domain vocabulary (TRD §3). Triage itself lands in
# Sprint 7; the alias keeps the AI interface aligned with the data model.
TriageLabel = Triage


@dataclass(frozen=True)
class SubgraphNode:
    id: str
    kind: str  # endpoint | page | model | table | role
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    source_sha: str | None = None


@dataclass(frozen=True)
class SubgraphEdge:
    src: str
    dst: str
    kind: str  # calls | implements | reads | writes | covers | observed_in


@dataclass(frozen=True)
class Subgraph:
    """A retrieved slice of the Brain, passed as grounded context to the model."""

    nodes: list[SubgraphNode] = field(default_factory=list)
    edges: list[SubgraphEdge] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Deterministically serialize to text for prompt assembly.

        Stable ordering (sorted) so the same subgraph always renders identically
        — important for caching, budget estimation, and reproducible tests.
        """
        lines: list[str] = []
        for node in sorted(self.nodes, key=lambda n: n.id):
            lines.append(f"[{node.kind}] {node.name} ({node.id})")
            for key in sorted(node.attributes):
                lines.append(f"  {key}: {node.attributes[key]}")
        for edge in sorted(self.edges, key=lambda e: (e.src, e.kind, e.dst)):
            lines.append(f"{edge.src} -{edge.kind}-> {edge.dst}")
        for index, snippet in enumerate(self.snippets):
            lines.append(f"--- snippet {index} ---\n{snippet}")
        return "\n".join(lines)


@dataclass(frozen=True)
class FailureEvidence:
    """Evidence about a failed test result, fed to triage (Sprint 7)."""

    test_case_id: str
    outcome: str  # fail | error
    message: str
    evidence_ref: str | None = None


@runtime_checkable
class AIProvider(Protocol):
    """The contract every AI provider satisfies. Provider-agnostic by design."""

    def generate(self, prompt: str, context: Subgraph, budget_tokens: int) -> str: ...

    def triage(self, failure: FailureEvidence) -> TriageLabel: ...
