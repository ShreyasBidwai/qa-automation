"""Deterministic document chunking for embedding (B9).

Pure + deterministic: the same content always yields the same chunks (and so the
same vectors). Greedy-packs paragraphs (blank-line separated) up to ``max_chars``;
a paragraph longer than the budget is hard-split on whitespace. No model, no I/O.
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def chunk_text(content: str, *, max_chars: int = 1000) -> list[str]:
    """Split ``content`` into ordered, non-empty chunks no longer than max_chars."""
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(content) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        for piece in _split_long(paragraph, max_chars):
            if not buffer:
                buffer = piece
            elif len(buffer) + 1 + len(piece) <= max_chars:
                buffer = f"{buffer}\n{piece}"
            else:
                chunks.append(buffer)
                buffer = piece
    if buffer:
        chunks.append(buffer)
    return chunks


def _split_long(text: str, max_chars: int) -> list[str]:
    """Hard-split an over-budget paragraph, preferring a whitespace boundary."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = window.rfind(" ")
        if cut <= 0:  # no usable space → hard cut at the limit
            cut = max_chars
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [p for p in pieces if p]
