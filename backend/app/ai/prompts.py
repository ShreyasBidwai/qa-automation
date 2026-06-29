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
