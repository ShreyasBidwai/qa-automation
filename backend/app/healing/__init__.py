"""Honest self-healing (B8, ADR-0040).

The thesis: heal the ADDRESSING (how a test locates its target), NEVER the
EXPECTATION (what it asserts). A newly-failing, previously-passing test is split
model-free into a LOCATION failure (couldn't reach its target → a candidate heal)
or an ASSERTION failure (reached it, value/behaviour wrong → a real finding,
never healed). Every heal is flagged, confidence-gated, and human-confirmable.
"""
