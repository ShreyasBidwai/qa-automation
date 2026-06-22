"""Assertion protection (B8, ADR-0040) — a heal re-addresses, never re-asserts.

``apply_route_heal`` rewrites only the route literal in the HTTP call; the
assertions are pinned. ``assertions_unchanged`` proves it independently, so the
guarantee is structural, not a convention.
"""

from __future__ import annotations

from app.healing.apply import (
    addressing_present,
    apply_route_heal,
    assertion_lines,
    assertions_unchanged,
)

_PEST = """<?php
test('create a user', function () {
    $response = $this->postJson('/api/users', ['name' => 'Ada']);
    $response->assertStatus(201);
    $response->assertJsonPath('data.name', 'Ada');
});
"""


def test_apply_rewrites_addressing_only() -> None:
    healed = apply_route_heal(_PEST, "api/users", "api/people")
    # the HTTP call now addresses the moved route, slash + quote style preserved.
    assert "$this->postJson('/api/people', ['name' => 'Ada'])" in healed
    assert "/api/users" not in healed
    # the expectations are byte-identical.
    assert "$response->assertStatus(201);" in healed
    assert "$response->assertJsonPath('data.name', 'Ada');" in healed
    assert assertions_unchanged(_PEST, healed)


def test_apply_preserves_no_leading_slash_style() -> None:
    code = "    $this->getJson('api/users');\n    $r->assertOk();\n"
    healed = apply_route_heal(code, "api/users", "api/people")
    assert "$this->getJson('api/people')" in healed  # no slash added


def test_old_path_absent_is_a_noop() -> None:
    healed = apply_route_heal(_PEST, "api/orders", "api/invoices")
    assert healed == _PEST  # nothing to re-address → caller declines to heal


def test_path_inside_an_assertion_is_never_rewritten() -> None:
    code = (
        "    $r = $this->getJson('/api/users');\n"
        "    $r->assertSee('/api/users');\n"  # the path appears in an assertion
        "    $r->assertStatus(200);\n"
    )
    healed = apply_route_heal(code, "api/users", "api/people")
    # the addressing line moved...
    assert "$this->getJson('/api/people')" in healed
    # ...but the assertion's literal is left exactly as authored.
    assert "$r->assertSee('/api/users');" in healed
    assert assertions_unchanged(code, healed)


def test_assertions_unchanged_catches_a_tampered_expectation() -> None:
    tampered = _PEST.replace("assertStatus(201)", "assertStatus(200)")
    # A change that touches an assertion is detected — the heal would be refused.
    assert not assertions_unchanged(_PEST, tampered)


def test_assertion_lines_and_addressing_present_helpers() -> None:
    lines = assertion_lines(_PEST)
    assert any("assertStatus(201)" in line for line in lines)
    assert any("assertJsonPath" in line for line in lines)
    assert not any("postJson" in line for line in lines)  # addressing is not an assertion
    assert addressing_present(_PEST, "api/users")
    assert not addressing_present(_PEST, "api/orders")
