"""Deterministic lexical signal for resolution (the ground-truth half).

Tokenizes the query and a node's document (reusing the embedding document
builder so lexical matching stays aligned with what is embedded) and scores
token overlap, with a whole-query substring bonus for exact name/uri hits. Works
with no model — this is what keeps the resolver testable with the stub provider
and resilient when embeddings are stale or absent.
"""

from __future__ import annotations

import re

from app.embeddings.document import build_node_document
from app.models.model_node import ModelNode

_TOKEN = re.compile(r"[a-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, splitting camelCase and non-alnum runs."""
    spaced = _CAMEL_BOUNDARY.sub(" ", text)
    return _TOKEN.findall(spaced.lower())


def lexical_score(query_text: str, node: ModelNode) -> float:
    """Token-overlap score in [0, 1]; 1.0 for an exact name/uri match."""
    query_tokens = tokenize(query_text)
    if not query_tokens:
        return 0.0

    document = build_node_document(node.kind, node.name, node.attributes)
    doc_tokens = set(tokenize(document))

    # Exact-ish whole-query match against the node name or uri → strongest.
    normalized_query = " ".join(query_tokens)
    name_norm = " ".join(tokenize(node.name))
    uri_norm = " ".join(tokenize(str(node.attributes.get("uri", ""))))
    if normalized_query in name_norm or (uri_norm and normalized_query in uri_norm):
        return 1.0

    matched = sum(1 for token in query_tokens if token in doc_tokens)
    return matched / len(query_tokens)
