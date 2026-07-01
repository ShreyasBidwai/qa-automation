"""Shared AI prompt fragments — provider-agnostic (TRD §6).

The generation instruction is the same regardless of which backend renders it
(`claude -p`, the Gemini API, …), so it lives here and both providers import it.
"""

from __future__ import annotations

GENERATE_INSTRUCTION = (
    "You are a test-generation engine for the QA Automation Platform. "
    "Using only the grounded context below, produce the requested test artifact. "
    "Do not invent endpoints, fields, or behavior absent from the context."
)

# Triage classifies WHY a generated test failed, so the operator sees whether a
# failure is a real defect or noise. The model must answer with exactly one label
# (parsing is tolerant, but a bare label keeps it cheap and unambiguous).
TRIAGE_INSTRUCTION = (
    "You are a failure-triage engine for the QA Automation Platform. A generated "
    "test failed; classify the ROOT CAUSE into exactly one label:\n"
    "- real-bug: the application under test is wrong (the test correctly caught it).\n"
    "- bad-test: the test itself is at fault (wrong assertion, missing setup/data).\n"
    "- flaky: a nondeterministic/timing failure, not a stable defect.\n"
    "- infra: an environment/tooling failure (DB down, timeout, connection refused), "
    "not application logic.\n"
    "- unknown: the evidence is insufficient to decide.\n"
    "Answer with ONLY the label and nothing else."
)
