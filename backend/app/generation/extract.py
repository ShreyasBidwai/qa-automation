"""Make model output directly runnable (B5→B6 follow-up).

Real models wrap generated code in markdown fences with lead-in prose and trailing
"Key decisions" tables; the test stub returns clean code, which is exactly why that
gap slipped the hermetic suite. ``extract_code`` pulls the executable code back out
(belt; the prompt asks for code-only as suspenders), and ``with_php_header`` makes
the PHP file VALID (``<?php`` first, the deterministic provenance header as real PHP
comments after it — not as raw text before ``<?php``, which PHP would echo).

Generated tests are PHPUnit-style Laravel feature CLASSES (``class …Test extends
TestCase``) — a single dialect both PHPUnit and Pest execute natively (Pest runs
PHPUnit test classes), so the executor is runner-agnostic. ``unique_class_name`` /
``rewrite_class_name`` force a globally-unique class name per file so several
generated tests can run in ONE invocation without a 'Cannot redeclare class' fatal
(Pest closures had no class to collide; PHPUnit classes do).

Deterministic + pure (no provider, no I/O) so it is exhaustively unit-testable.
"""

from __future__ import annotations

import hashlib
import re

# A ```lang\n…\n``` block. Non-greedy so multiple blocks are matched separately.
_FENCE_RE = re.compile(r"```[ \t]*([\w.+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)

# Fence languages we treat as code, and content that "looks like" PHP/TS even without
# a language tag (so an unlabelled fence still wins over a prose fence). The PHP hints
# key on the PHPUnit class/method shape (namespace / use / class / visibility /
# function), not Pest globals.
_CODE_LANGS = frozenset({"php", "ts", "typescript", "js", "javascript"})
_CODE_HINT_RE = re.compile(
    r"<\?php|^\s*(?:namespace|use|declare|abstract|final|class|public|protected"
    r"|private|function|import)\b",
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


# A test method's opening: ``public function test_foo(): void {`` (return type
# optional). Used to inject a skip as the method's first statement.
_METHOD_OPEN_RE = re.compile(r"function\s+\w+\s*\([^)]*\)\s*(?::\s*[\w\\]+\s*)?\{")


def skip_if_uses_factory(code: str, reason: str) -> str:
    """Honestly skip a PHPUnit test that calls ``::factory()`` (ADR-0037).

    When the target defines no model factories, a generated test that still calls
    ``Model::factory()`` would HARD-FAIL on the missing factory. Rather than emit a
    broken test, inject ``$this->markTestSkipped(reason)`` as the FIRST statement of
    the test method so PHPUnit/Pest report it as skipped (honest) before the factory
    call runs, until real precondition seeding lands (B10). Deterministic transform
    on the ``public function test_…(): void { … }`` shape; a no-op if the code uses
    no factory or has no recognizable test method.
    """
    if "::factory(" not in code:
        return code
    match = _METHOD_OPEN_RE.search(code)
    if match is None:
        return code
    skip = f"\n        $this->markTestSkipped({_php_single_quoted(reason)});"
    return code[: match.end()] + skip + code[match.end() :]


def _php_identifier(text: str) -> str:
    """A safe PHP identifier fragment from text (non-empty, never digit-led)."""
    ident = re.sub(r"\W+", "_", text.strip()).strip("_")
    if not ident:
        ident = "case"
    if ident[0].isdigit():
        ident = f"c_{ident}"
    return ident


def phpunit_method_name(case_name: str) -> str:
    """A valid PHPUnit test method name (``test_…``) for a case name."""
    return "test_" + _php_identifier(case_name).lower()


def unique_class_name(case_name: str, seed: str) -> str:
    """A deterministic, GLOBALLY-UNIQUE PHPUnit test class name.

    ``case_name`` makes it human-readable; ``seed`` (e.g. ``"<method> <uri> <case>"``)
    is hashed so two files never share a class name — several generated tests run in
    one ``pest``/``phpunit`` invocation, and duplicate class names would fatal with
    'Cannot redeclare class'. Pure/deterministic (same inputs → same name).
    """
    token = hashlib.sha256(seed.encode()).hexdigest()[:10]
    camel = "".join(part.capitalize() for part in re.split(r"\W+", case_name) if part)
    if not camel or not camel[0].isalpha():
        camel = "Generated" + camel
    return f"{camel}_{token}Test"


def rewrite_class_name(code: str, class_name: str) -> str:
    """Force the (first) ``class <X>`` declaration to ``class <class_name>``.

    The model names the class freely; rewriting to a deterministic unique name
    guarantees no cross-file collisions. A no-op if the code declares no class.
    """
    return re.sub(r"\bclass\s+\w+", f"class {class_name}", code, count=1)
