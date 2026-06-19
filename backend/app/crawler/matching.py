"""Match an observed network call to an existing endpoint node (the bridge).

This is the cross-layer link the crawler contributes: an intercepted frontend
API call → the backend endpoint node it hit. Matching is by HTTP method + URL
path against endpoint nodes' ``{method, uri}`` (the shape the T2.2 ingester
writes). Exact matches are highest-confidence; ``{param}`` path templates match
concrete paths at a lower confidence. Pure + deterministic.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.models.model_node import ModelNode

from .types import NetworkCall

# Observed confidence tiers: an exact path match is stronger evidence than a
# parameterised-template match (which could over-match a sibling route).
CONFIDENCE_EXACT = 0.9
CONFIDENCE_TEMPLATE = 0.7


def _normalize_uri(uri: str) -> str:
    uri = uri.strip().lstrip("/")
    if len(uri) > 1 and uri.endswith("/"):
        uri = uri.rstrip("/")
    return uri


def _template_pattern(uri: str) -> re.Pattern[str]:
    """``api/users/{id}`` → regex matching ``api/users/<anything-but-/>``."""
    segments = [
        r"[^/]+" if seg.startswith("{") and seg.endswith("}") else re.escape(seg)
        for seg in uri.split("/")
    ]
    return re.compile("^" + "/".join(segments) + "$")


class EndpointMatcher:
    """Precomputed lookup from (method, path) → endpoint node + confidence."""

    def __init__(self, endpoints: list[ModelNode]) -> None:
        self._exact: dict[tuple[str, str], ModelNode] = {}
        self._templates: list[tuple[str, re.Pattern[str], ModelNode]] = []
        # Deterministic order: sort by node name so a path matching two templates
        # always resolves to the same endpoint.
        for node in sorted(endpoints, key=lambda n: n.name):
            method = str(node.attributes.get("method", "")).upper()
            uri = _normalize_uri(str(node.attributes.get("uri", "")))
            if not method or not uri:
                continue
            self._exact.setdefault((method, uri), node)
            if "{" in uri:
                self._templates.append((method, _template_pattern(uri), node))

    def match(self, call: NetworkCall) -> tuple[ModelNode, float] | None:
        """The endpoint node a call hit (+ confidence), or None if unmatched."""
        method = call.method.upper()
        path = _normalize_uri(urlsplit(call.url).path)
        exact = self._exact.get((method, path))
        if exact is not None:
            return exact, CONFIDENCE_EXACT
        for tmpl_method, pattern, node in self._templates:
            if tmpl_method == method and pattern.match(path):
                return node, CONFIDENCE_TEMPLATE
        return None
