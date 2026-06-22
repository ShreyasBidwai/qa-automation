"""The EndpointSpec's URI + auth come from INGEST (route:list), not by hand.

No production change — a documenting assertion (B5→B6, ADR-0037). The B5 smoke's
404 was a *hand-built-spec* artifact: it used uri="api/users", auth_required=False,
but the fixture registers the route at "users" behind `auth` middleware. The real
path derives the spec from `artisan route:list`, so uri + auth are accurate (the
generated test would hit "users" and authenticate) — proven here with canned
route:list output, hermetically (no PHP).
"""

from __future__ import annotations

import json

from app.ingestion.laravel.route_list import all_route_facts

# What `php artisan route:list --json` emits for the fixture's users.store route.
_ROUTE_LIST_JSON = json.dumps(
    [
        {
            "method": "POST",
            "uri": "users",
            "name": "users.store",
            "action": "App\\Http\\Controllers\\UserController@store",
            "middleware": ["auth"],
        }
    ]
)


def test_endpoint_uri_and_auth_are_ingest_derived_not_hand_built() -> None:
    facts = all_route_facts(_ROUTE_LIST_JSON)
    assert len(facts) == 1
    route = facts[0]

    # Ingest yields the REAL uri ("users") + auth (True from `auth` middleware) —
    # NOT the smoke's hand-built ("api/users", auth_required=False) that 404'd.
    assert route.uri == "users"
    assert route.uri != "api/users"
    assert route.method == "POST"
    assert route.auth_required is True
    assert route.name == "users.store"
