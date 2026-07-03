"""Module derivation — grouping the Brain's testable targets by feature area (pure)."""

from __future__ import annotations

import uuid

from app.brain.modules import (
    aggregate_modules,
    derive_module_key,
    module_label,
)
from app.models.enums import NodeKind
from tests.factories import make_node


def test_endpoint_module_is_the_first_meaningful_segment() -> None:
    # "METHOD uri" → strip the method + api/version prefixes → the resource segment.
    assert derive_module_key(NodeKind.ENDPOINT, "POST api/v1/orders") == "orders"
    assert derive_module_key(NodeKind.ENDPOINT, "GET api/v1/orders/{id}") == "orders"
    assert derive_module_key(NodeKind.ENDPOINT, "GET api/users/{id}/roles") == "users"


def test_page_module_is_derived_from_the_path() -> None:
    assert derive_module_key(NodeKind.PAGE, "/orders/create") == "orders"
    assert derive_module_key(NodeKind.PAGE, "orders") == "orders"


def test_no_module_for_a_root_or_all_prefix_path() -> None:
    assert derive_module_key(NodeKind.ENDPOINT, "GET api/v1") is None
    assert derive_module_key(NodeKind.PAGE, "/") is None


def test_module_label_humanises_the_key() -> None:
    assert module_label("orders") == "Orders"
    assert module_label("order-items") == "Order items"
    assert module_label("user_profiles") == "User profiles"


def test_aggregate_groups_by_module_with_per_kind_counts_and_order() -> None:
    project_id = uuid.uuid4()
    nodes = [
        make_node(project_id, kind=NodeKind.ENDPOINT, name="GET api/v1/orders"),
        make_node(project_id, kind=NodeKind.ENDPOINT, name="POST api/v1/orders"),
        make_node(project_id, kind=NodeKind.PAGE, name="/orders"),
        make_node(project_id, kind=NodeKind.ENDPOINT, name="GET api/v1/users"),
        # A model/table node is not testable → never a module.
        make_node(project_id, kind=NodeKind.MODEL, name="Order"),
    ]
    modules = aggregate_modules(nodes)

    assert [m.key for m in modules] == ["orders", "users"]  # most targets first
    orders = modules[0]
    assert orders.label == "Orders"
    assert orders.endpoint_count == 2
    assert orders.page_count == 1
    assert orders.total == 3
    assert modules[1].key == "users" and modules[1].total == 1
