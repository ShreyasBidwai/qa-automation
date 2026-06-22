"""Make model output directly runnable (B5→B6 follow-up).

Real models wrap generated code in markdown fences with lead-in prose and trailing
"Key decisions" tables; the test stub returns clean code, which is exactly why that
gap slipped the hermetic suite. ``extract_code`` pulls the executable code back out
(belt; the prompt asks for code-only as suspenders), and ``with_php_header`` makes
the PHP file VALID (``<?php`` first, the deterministic provenance header as real PHP
comments after it — not as raw text before ``<?php``, which PHP would echo).

Deterministic + pure (no provider, no I/O) so it is exhaustively unit-testable.
"""

from __future__ import annotations

import re

# A ```lang\n…\n``` block. Non-greedy so multiple blocks are matched separately.
_FENCE_RE = re.compile(r"```[ \t]*([\w.+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)

# Fence languages we treat as code, and content that "looks like" PHP/Pest/TS even
# without a language tag (so an unlabelled fence still wins over a prose fence).
_CODE_LANGS = frozenset({"php", "pest", "ts", "typescript", "js", "javascript"})
_CODE_HINT_RE = re.compile(
    r"<\?php|^\s*(?:use|it|test|uses|namespace|declare|function|import|expect)\b",
    re.MULTILINE,
)


def extract_code(text: str) -> str:
    """Return the executable code from a model response.

    Handles: a single fenced block, MULTIPLE fenced blocks (picks the largest
    code-looking one — a whole test, not a snippet), an unlabelled fence, and the
    no-fence case (drops any lead-in prose before the first code line). Clean
    code-only input (the stub) passes through unchanged.
    """
    blocks: list[tuple[str, str]] = _FENCE_RE.findall(text or "")
    if blocks:
        coded = [
            content
            for lang, content in blocks
            if lang.lower() in _CODE_LANGS or _CODE_HINT_RE.search(content)
        ]
        candidates = coded or [content for _lang, content in blocks]
        return max(candidates, key=lambda c: len(c.strip())).strip()
    return _strip_lead_in_prose(text or "").strip()


def _strip_lead_in_prose(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(
            ("<?php", "//", "/*", "import ", "use ")
        ) or _CODE_HINT_RE.search(line):
            return "\n".join(lines[index:])
    return text  # no code-looking line found → return as-is (a model failure)


def with_php_header(code: str, header: str) -> str:
    """A VALID PHP file: ``<?php`` first, then ``header`` as PHP comments, then code.

    The header must live *after* ``<?php`` — anything before it is literal output,
    not a comment. Tolerates code that already starts with (or omits) ``<?php``.
    """
    code = code.strip()
    if code.startswith("<?php"):
        code = code[len("<?php") :].lstrip("\n")
    return f"<?php\n{header}\n\n{code}\n"


def with_comment_header(code: str, header: str) -> str:
    """Leading ``//`` comment header for a TS/JS file (valid at the top of a spec)."""
    return f"{header}\n\n{code.strip()}\n"


def _php_single_quoted(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def skip_if_uses_factory(code: str, reason: str) -> str:
    """Honestly skip a Pest test that calls ``::factory()`` (ADR-0037).

    When the target defines no model factories, a generated test that still calls
    ``Model::factory()`` would HARD-FAIL on the missing factory. Rather than emit a
    broken test, chain ``->skip(reason)`` onto the test closure so it is reported as
    skipped (honest) until real precondition seeding lands (B10). Deterministic
    transform on Pest's ``it(…, function () { … });`` shape; a no-op if the code
    doesn't use a factory or can't be safely transformed.
    """
    if "::factory(" not in code:
        return code
    close = code.rfind("});")
    if close == -1:
        return code
    skip = "})->skip(" + _php_single_quoted(reason) + ");"
    return code[:close] + skip + code[close + len("});") :]
