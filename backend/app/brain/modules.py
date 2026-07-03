"""Modules — a functional grouping of the Brain's testable targets (ADR-0061).

A "module" is a feature area of the app (Orders, Users, Auth…). It is DERIVED, not
stored: a testable node's module is the first meaningful segment of its URI/path,
after any ``api``/version prefix. So ``POST api/v1/orders``, ``GET api/v1/orders/{id}``
and the page ``/orders`` all belong to the ``orders`` module.

This lets a run be scoped to only the modules a QA cares about — and, composed with the
layer scope (ADR-0052), to only that module's FRONTEND (its page targets → the crawl +
E2E) or its API (its endpoint targets). No new execution path: a module is a target
filter, exactly like the layer filter.

Pure: derivation has no I/O (fully unit-testable); aggregation takes already-read nodes.
Module keys are only ever compared as strings — never fed into SQL, a path, a URL host,
or a command — so they carry no injection surface.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.models.enums import NodeKind
from app.models.model_node import ModelNode

# Transport / versioning segments that are never a module on their own.
_SKIP_SEGMENTS = frozenset({"api", "apis"})
_VERSION_RE = re.compile(r"^v\d+$")
# The node kinds that carry a URI/path we can group into a module (the testable ones).
MODULE_KINDS: tuple[NodeKind, ...] = (NodeKind.ENDPOINT, NodeKind.PAGE)


def _uri_of(kind: NodeKind, name: str) -> str:
    """The URI/path carried by a node's name. An endpoint node is named ``"METHOD uri"``
    (ingester.py); a page node is named by its path."""
    if kind is NodeKind.ENDPOINT:
        _, _, uri = name.partition(" ")
        return uri or name
    return name


def derive_module_key(kind: NodeKind, name: str) -> str | None:
    """The module a testable node belongs to — the first meaningful path segment — or
    ``None`` when none can be derived (a root path, or an all-prefix URI). Deterministic
    and case-insensitive (keys are always lower-case)."""
    uri = _uri_of(kind, name)
    for raw in uri.strip("/").split("/"):
        seg = raw.strip().lower()
        if not seg or seg in _SKIP_SEGMENTS or _VERSION_RE.match(seg):
            continue
        # A path parameter (``{id}``, ``:id``, ``<id>``) is not a module.
        if seg[0] in "{:<":
            continue
        return seg
    return None


def module_label(key: str) -> str:
    """A human label for a module key (``"order-items"`` → ``"Order items"``)."""
    words = " ".join(part for part in re.split(r"[-_]+", key) if part)
    return words.capitalize() if words else key


@dataclass(frozen=True)
class ModuleSummary:
    key: str
    label: str
    endpoint_count: int
    page_count: int

    @property
    def total(self) -> int:
        return self.endpoint_count + self.page_count


def aggregate_modules(nodes: list[ModelNode]) -> list[ModuleSummary]:
    """Group testable nodes into modules with per-kind counts, most targets first
    (ties broken by key) so the biggest feature areas lead the picker."""
    endpoints: dict[str, int] = defaultdict(int)
    pages: dict[str, int] = defaultdict(int)
    for node in nodes:
        if node.kind not in MODULE_KINDS:
            continue
        key = derive_module_key(node.kind, node.name)
        if key is None:
            continue
        if node.kind is NodeKind.ENDPOINT:
            endpoints[key] += 1
        else:
            pages[key] += 1

    keys = set(endpoints) | set(pages)
    summaries = [
        ModuleSummary(
            key=key,
            label=module_label(key),
            endpoint_count=endpoints.get(key, 0),
            page_count=pages.get(key, 0),
        )
        for key in keys
    ]
    return sorted(summaries, key=lambda module: (-module.total, module.key))
