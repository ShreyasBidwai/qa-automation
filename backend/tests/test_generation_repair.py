"""Loop 0 self-repair (ADR-0070/C3): a render that comes back malformed (prose, not a
test class) triggers ONE bounded retry with the defect named; a valid first attempt is
never retried. Deterministic + AI-free (tests aren't mypy-checked, so a fake provider
is fine)."""

from __future__ import annotations

from app.generation.plan import plan_cases
from app.generation.render import render_script
from app.ingestion.models import EndpointSpec

_VALID = (
    "<?php\nnamespace Tests\\Feature;\n"
    "class GenTest extends Tests\\TestCase\n{\n"
    "    public function test_x(): void {}\n}\n"
)


def _api_spec() -> EndpointSpec:
    return EndpointSpec(
        method="GET",
        uri="api/orders",
        route_name="orders.index",
        auth_required=False,
        path_params=[],
        query_params=[],
        validation_fields=[],
        is_api=True,
    )


class _ScriptedProvider:
    """Returns the queued outputs in order, recording how many times it was called."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self.calls = 0

    def generate(self, prompt: str, context: object, budget_tokens: int) -> str:
        out = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return out


def test_render_self_repairs_a_malformed_first_attempt() -> None:
    spec = _api_spec()
    case = plan_cases(spec)[0]
    # First attempt is prose (not a class); the retry returns a real test class.
    provider = _ScriptedProvider(["Sorry, I can't help with that.", _VALID])

    out = render_script(provider, spec, case, 4000)
    assert provider.calls == 2  # retried exactly once
    assert "extends" in out and "test_x" in out


def test_render_does_not_retry_a_valid_first_attempt() -> None:
    spec = _api_spec()
    case = plan_cases(spec)[0]
    provider = _ScriptedProvider([_VALID])

    render_script(provider, spec, case, 4000)
    assert provider.calls == 1  # valid first try → no wasted second call
