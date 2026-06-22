"""Apply an addressing heal to a test script — and prove the assertions survived.

The hard rule (ADR-0040): a heal may rewrite HOW a test locates its target; it may
NEVER change WHAT it asserts. This module enforces that *structurally*, not by
convention:

  - ``apply_route_heal`` substitutes the addressing token (the route path inside
    the HTTP-call string literal) and is forbidden from touching any line that
    carries an assertion — it skips those lines entirely.
  - ``assertions_unchanged`` independently re-derives the assertion lines from the
    before/after code and checks they are byte-identical. It does not know how the
    rewrite was done, so it is a genuine check, not a tautology: a future change
    that let an assertion move would be caught here, and the caller refuses the
    heal.

So the safety property is verified by a function that is independent of the
function that produces the change.
"""

from __future__ import annotations

import re

# A line that carries an oracle (an expectation). If a line matches, the rewrite
# leaves it completely alone, and the verifier pins it. Covers Pest/Laravel
# (``assertStatus``, ``assertJson*`` …), Playwright/JS (``expect(``, ``.toBe`` …)
# and plain pytest (``assert``).
_ASSERTION_LINE_RE = re.compile(
    r"""
    ->\s*assert            # Laravel fluent assertions: ->assertStatus(...)
  | \bassert[A-Z]\w*\s*\(  # bare assertJson(...), assertSee(...)
  | \bexpect\s*\(          # expect(...).toBe(...)
  | \.to[A-Z]\w*\s*\(      # .toBe(...), .toHaveText(...)
  | ^\s*assert\b           # pytest: assert ...
    """,
    re.VERBOSE,
)


def _is_assertion_line(line: str) -> bool:
    return _ASSERTION_LINE_RE.search(line) is not None


def assertion_lines(code: str) -> list[str]:
    """The assertion-bearing lines of ``code``, in order (the protected block)."""
    return [line for line in code.splitlines() if _is_assertion_line(line)]


def assertions_unchanged(before: str, after: str) -> bool:
    """True iff ``before`` and ``after`` have identical assertion lines.

    The structural guarantee behind every heal: the addressing may differ, the
    expectations may not.
    """
    return assertion_lines(before) == assertion_lines(after)


def _path_literal_re(path: str) -> re.Pattern[str]:
    """Match ``path`` as a whole route inside a string literal.

    Anchored to quotes so it never rewrites a path that is merely a substring of a
    longer one, and the optional leading slash is captured so the original style
    (``'/api/users'`` vs ``'api/users'``) is preserved on substitution.
    """
    body = re.escape(path.strip("/"))
    return re.compile(r"(['\"])(/?)" + body + r"(['\"])")


def apply_route_heal(code: str, old_path: str, new_path: str) -> str:
    """Re-address ``code`` from ``old_path`` to ``new_path`` — addressing only.

    Substitutes the old route path with the new one inside HTTP-call string
    literals, line by line, and NEVER on an assertion line. Quote style and any
    leading slash are preserved. If the old path does not appear in any
    non-assertion line, the code is returned unchanged (the caller treats an
    unchanged result as "could not locate the addressing" and declines to heal).
    """
    pattern = _path_literal_re(old_path)
    new_body = new_path.strip("/")

    def _sub(match: re.Match[str]) -> str:
        open_q, slash, close_q = match.group(1), match.group(2), match.group(3)
        return f"{open_q}{slash}{new_body}{close_q}"

    out: list[str] = []
    for line in code.splitlines(keepends=True):
        if _is_assertion_line(line):
            out.append(line)  # the protected block — never rewritten
        else:
            out.append(pattern.sub(_sub, line))
    return "".join(out)


def addressing_present(code: str, path: str) -> bool:
    """True iff ``path`` appears as a route literal in a non-assertion line."""
    pattern = _path_literal_re(path)
    return any(
        pattern.search(line)
        for line in code.splitlines()
        if not _is_assertion_line(line)
    )
