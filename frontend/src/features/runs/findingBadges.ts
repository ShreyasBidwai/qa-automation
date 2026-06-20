/**
 * Map a finding's fields to quiet badge specs (design-direction.md): semantic
 * background + same-family text, sentence-case label. Colour never the sole
 * signal — every badge carries a word.
 */

export type BadgeLevel = "pass" | "fail" | "flaky" | "info" | "neutral";

export interface BadgeSpec {
  level: BadgeLevel;
  label: string;
}

export function severitySpec(severity: string): BadgeSpec {
  switch (severity) {
    case "critical":
      return { level: "fail", label: "Critical" };
    case "major":
      return { level: "flaky", label: "Major" };
    case "minor":
      return { level: "neutral", label: "Minor" };
    default:
      return { level: "neutral", label: severity };
  }
}

export function layerSpec(layer: string): BadgeSpec {
  // Layer is categorical, not semantic — a quiet neutral tag.
  return { level: "neutral", label: layer };
}

export function confidenceSpec(oracleSource: string): BadgeSpec {
  switch (oracleSource) {
    case "rule-derived":
      return { level: "pass", label: "Rule-derived" };
    case "spec-grounded":
      return { level: "pass", label: "Spec-grounded" };
    case "characterization":
      return { level: "flaky", label: "Behaviour-changed" };
    default:
      return { level: "neutral", label: oracleSource };
  }
}

export function statusSpec(status: string): BadgeSpec {
  switch (status) {
    case "new":
      return { level: "info", label: "New" };
    case "regression":
      return { level: "fail", label: "Regression" };
    case "flaky":
      return { level: "flaky", label: "Flaky" };
    case "known":
      return { level: "neutral", label: "Known" };
    default:
      return { level: "neutral", label: status };
  }
}
