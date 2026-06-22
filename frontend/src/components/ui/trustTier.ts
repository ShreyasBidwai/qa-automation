/**
 * Trust-tier mapping + palette for the oracle-trust mark (see TrustMark.tsx).
 * Kept in a plain module so the component file only exports components.
 */

export type TrustTier = "rule" | "char" | "spec" | "unknown";

export interface TierViz {
  tier: TrustTier;
  /** The plain tier name, shown as the label and the accessible name. */
  name: string;
  /** Pill chrome: soft bg + border + same-family text. */
  pill: string;
  /** Inline label colour (no chrome). */
  text: string;
}

export const TRUST_VIZ: Record<TrustTier, TierViz> = {
  rule: {
    tier: "rule",
    name: "rule-derived",
    pill: "border-trust-rule-border bg-trust-rule-bg text-trust-rule-fg",
    text: "text-trust-rule-fg",
  },
  char: {
    tier: "char",
    name: "characterization",
    pill: "border-trust-char-border bg-trust-char-bg text-trust-char-fg",
    text: "text-trust-char-fg",
  },
  spec: {
    tier: "spec",
    name: "spec-grounded",
    pill: "border-trust-spec-border bg-trust-spec-bg text-trust-spec-fg",
    text: "text-trust-spec-fg",
  },
  unknown: {
    tier: "unknown",
    name: "unknown",
    pill: "border-border bg-status-neutral-bg text-status-neutral-fg",
    text: "text-muted-foreground",
  },
};

/** Map an API `oracle_source` string to its trust tier. */
export function trustTier(oracleSource: string): TrustTier {
  switch (oracleSource) {
    case "rule-derived":
      return "rule";
    case "characterization":
      return "char";
    case "spec-grounded":
      return "spec";
    default:
      return "unknown";
  }
}
