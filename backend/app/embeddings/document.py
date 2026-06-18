"""Deterministic node-document builder for embedding (better retrieval).

Embeds a short text built from kind + name + key attributes rather than the bare
name — e.g. "endpoint POST checkout/discount name=checkout.discount
controller=DiscountController@apply auth=True fields=code,cart_id". Pure and
deterministic so the same node always yields the same document (and vector).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.models.enums import NodeKind


def _csv(values: Any) -> str:
    if isinstance(values, list | tuple):
        return ",".join(str(v) for v in values)
    return str(values)


def _endpoint(name: str, attrs: Mapping[str, Any]) -> str:
    method = str(attrs.get("method", "")).strip()
    uri = str(attrs.get("uri", name)).strip()
    parts = [f"endpoint {method} {uri}".strip()]
    if attrs.get("name"):
        parts.append(f"name={attrs['name']}")
    if attrs.get("action"):
        parts.append(f"controller={attrs['action']}")
    if attrs.get("auth_required") is not None:
        parts.append(f"auth={attrs['auth_required']}")
    validation = attrs.get("validation")
    if isinstance(validation, Mapping) and validation.get("fields"):
        parts.append(f"fields={_csv(validation['fields'])}")
    return " ".join(parts)


def _model(name: str, attrs: Mapping[str, Any]) -> str:
    parts = [f"model {name}"]
    if attrs.get("table"):
        parts.append(f"table={attrs['table']}")
    if attrs.get("fillable"):
        parts.append(f"fillable={_csv(attrs['fillable'])}")
    relationships = attrs.get("relationships")
    if isinstance(relationships, list):
        related = [
            str(r.get("related", "")) for r in relationships if isinstance(r, Mapping)
        ]
        related = [r for r in related if r]
        if related:
            parts.append(f"relations={_csv(related)}")
    return " ".join(parts)


def build_node_document(
    kind: NodeKind, name: str, attributes: Mapping[str, Any]
) -> str:
    if kind is NodeKind.ENDPOINT:
        return _endpoint(name, attributes)
    if kind is NodeKind.MODEL:
        return _model(name, attributes)
    if kind is NodeKind.TABLE:
        columns = attributes.get("columns")
        if columns:
            return f"table {name} columns={_csv(columns)}"
        return f"table {name}"
    if kind is NodeKind.ROLE:
        return f"role {name}"
    return f"{kind.value} {name}"


def content_sha(
    kind: NodeKind, name: str, attributes: Mapping[str, Any], document: str
) -> str:
    """Deterministic hash of a node's EXTRACTED content — the ADR-0010 cache key.

    Keyed on the extracted facts that define the node (kind + name + attributes +
    its node-document), NOT the raw file or repo HEAD: identical extracted
    content yields an identical content_sha even if unrelated code or whitespace
    changed, so re-ingest only re-embeds nodes whose meaning actually changed.
    """
    payload = json.dumps(
        {
            "kind": kind.value,
            "name": name,
            "attributes": attributes,
            "document": document,
        },
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
