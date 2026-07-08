"""The generation prompt/strategy version (ADR-0070).

Bumped whenever the generation prompt or strategy changes materially, so the flywheel
can attribute a shift in test quality to the change (vs the model or the customer mix).
Stamped onto each AI-generated ``TestCase`` (``gen_prompt_version``) at creation, and
read back at execution to label its outcome. A leaf module (a bare constant) so both
generators import it without an import cycle.
"""

from __future__ import annotations

PROMPT_VERSION = "2026-07-v1"
