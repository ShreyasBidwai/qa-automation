import type { Finding } from "@/lib/api/types";

/**
 * Derive the run-dashboard headline stats from the ranked findings (design brief
 * screen 7 stat cards). Pure + total over the list, so the cards read straight
 * from the same data the list shows — no second source, nothing invented.
 */

export interface SeverityCounts {
  critical: number;
  major: number;
  minor: number;
}

export function severityCounts(findings: Finding[]): SeverityCounts {
  const counts: SeverityCounts = { critical: 0, major: 0, minor: 0 };
  for (const f of findings) {
    if (f.severity === "critical") counts.critical += 1;
    else if (f.severity === "major") counts.major += 1;
    else if (f.severity === "minor") counts.minor += 1;
  }
  return counts;
}

export interface HistoryCounts {
  new: number;
  regression: number;
}

export function historyCounts(findings: Finding[]): HistoryCounts {
  const counts: HistoryCounts = { new: 0, regression: 0 };
  for (const f of findings) {
    if (f.status === "new") counts.new += 1;
    else if (f.status === "regression") counts.regression += 1;
  }
  return counts;
}

export interface ConfidenceMix {
  rule: number;
  characterization: number;
  spec: number;
  /** The dominant oracle source, or null when there are no findings. */
  dominant: string | null;
}

/** Tally findings by oracle tier and name the dominant one (for "Mostly …"). */
export function confidenceMix(findings: Finding[]): ConfidenceMix {
  const mix: ConfidenceMix = {
    rule: 0,
    characterization: 0,
    spec: 0,
    dominant: null,
  };
  for (const f of findings) {
    if (f.oracle_source === "rule-derived") mix.rule += 1;
    else if (f.oracle_source === "characterization") mix.characterization += 1;
    else if (f.oracle_source === "spec-grounded") mix.spec += 1;
  }
  // Prefer the stronger tiers on a tie (rule > spec > characterization).
  const ranked: [string, number][] = [
    ["rule-derived", mix.rule],
    ["spec-grounded", mix.spec],
    ["characterization", mix.characterization],
  ];
  const top = ranked.reduce((best, cur) => (cur[1] > best[1] ? cur : best));
  mix.dominant = top[1] > 0 ? top[0] : null;
  return mix;
}

/** A short label for the confidence card, e.g. "Mostly rule-derived". */
export function confidenceLabel(mix: ConfidenceMix): string {
  if (!mix.dominant) return "—";
  const total = mix.rule + mix.characterization + mix.spec;
  const dominantCount =
    mix.dominant === "rule-derived"
      ? mix.rule
      : mix.dominant === "spec-grounded"
        ? mix.spec
        : mix.characterization;
  // All of one tier reads as a clean statement; otherwise it's the lean.
  return dominantCount === total ? `All ${mix.dominant}` : `Mostly ${mix.dominant}`;
}
