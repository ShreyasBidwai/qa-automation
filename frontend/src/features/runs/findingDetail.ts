import type { Finding } from "@/lib/api/types";

/**
 * Derive cross-layer + failure detail from a finding. The `root_cause_key` (which
 * the API DOES expose) encodes the anchor (deepest failing node) and a failure
 * signature, e.g. `endpoint=POST api/orders#fail|status=500`. We parse it to know
 * the failing hop and the failure shape, and combine with `location` (when the
 * API exposes it) for the full UI → API → DB path.
 */

export type AnchorKind = "page" | "endpoint" | "table" | "none";

export interface ParsedKey {
  anchorKind: AnchorKind;
  anchorValue: string;
  signature: string;
}

export function parseRootCauseKey(key: string): ParsedKey {
  const hash = key.indexOf("#");
  const anchor = hash === -1 ? key : key.slice(0, hash);
  const signature = hash === -1 ? "" : key.slice(hash + 1);
  const eq = anchor.indexOf("=");
  if (eq === -1) return { anchorKind: "none", anchorValue: anchor, signature };
  const kind = anchor.slice(0, eq);
  const value = anchor.slice(eq + 1);
  const anchorKind: AnchorKind =
    kind === "page" || kind === "endpoint" || kind === "table" ? kind : "none";
  return { anchorKind, anchorValue: value, signature };
}

export interface ParsedSignature {
  outcome: string;
  status: string | null;
  assertions: string[];
}

export function parseSignature(signature: string): ParsedSignature {
  const parts = signature.split("|").filter(Boolean);
  let status: string | null = null;
  let assertions: string[] = [];
  for (const part of parts.slice(1)) {
    if (part.startsWith("status=")) status = part.slice("status=".length);
    else if (part.startsWith("assert="))
      assertions = part.slice("assert=".length).split(",").filter(Boolean);
  }
  return { outcome: parts[0] ?? "", status, assertions };
}

/** A one-line, plain description of the failure (from the key signature). */
export function failureLine(finding: Finding): string | null {
  const { anchorKind, anchorValue, signature } = parseRootCauseKey(
    finding.root_cause_key,
  );
  if (anchorKind === "none") return null;
  const sig = parseSignature(signature);
  if (sig.status) return `${anchorValue} returned ${sig.status}`;
  if (sig.outcome === "error") return `${anchorValue} errored`;
  return `${anchorValue} failed`;
}

export type Tier = "UI" | "API" | "DB";

export interface RibbonHop {
  tier: Tier;
  label: string;
  failing: boolean;
}

export interface Ribbon {
  hops: RibbonHop[];
  partial: boolean; // true → derived from the key alone (location not exposed)
  available: boolean;
}

const TIER: Record<Exclude<AnchorKind, "none">, Tier> = {
  page: "UI",
  endpoint: "API",
  table: "DB",
};

/** Build the UI → API → DB ribbon, marking the failing hop (the key's anchor). */
export function buildRibbon(finding: Finding): Ribbon {
  const parsed = parseRootCauseKey(finding.root_cause_key);
  const failing = new Set(
    parsed.anchorValue
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
  const isFailing = (kind: AnchorKind, label: string) =>
    parsed.anchorKind === kind && (failing.has(label) || failing.size === 0);

  const location = finding.location ?? null;
  const pathCount =
    (location?.page ? 1 : 0) +
    (location?.endpoints?.length ?? 0) +
    (location?.tables?.length ?? 0);

  if (location && pathCount > 0) {
    const hops: RibbonHop[] = [];
    if (location.page) {
      hops.push({
        tier: "UI",
        label: location.page,
        failing: isFailing("page", location.page),
      });
    }
    for (const endpoint of location.endpoints ?? []) {
      hops.push({
        tier: "API",
        label: endpoint,
        failing: isFailing("endpoint", endpoint),
      });
    }
    for (const table of location.tables ?? []) {
      hops.push({ tier: "DB", label: table, failing: isFailing("table", table) });
    }
    return { hops, partial: false, available: true };
  }

  // No location field — degrade to just the failing node from the key.
  if (parsed.anchorKind !== "none") {
    const tier = TIER[parsed.anchorKind];
    const hops = parsed.anchorValue
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)
      .map((label) => ({ tier, label, failing: true }));
    return { hops, partial: true, available: hops.length > 0 };
  }

  return { hops: [], partial: true, available: false };
}

/** Plain-language reason a finding is high-confidence vs a change to confirm. */
export function confidenceRationale(oracleSource: string): string {
  switch (oracleSource) {
    case "rule-derived":
      return "Rule-derived — this breaks an explicit rule, so it's a high-confidence bug to fix.";
    case "spec-grounded":
      return "Spec-grounded — checked against a stated requirement; a high-confidence bug.";
    case "characterization":
      return "Behaviour-changed — this only pins current behaviour, so confirm whether the change is intended.";
    default:
      return `Confidence source: ${oracleSource}.`;
  }
}

/** One-line meaning of a cross-run status. */
export function statusMeaning(status: string): string {
  switch (status) {
    case "new":
      return "New — first seen in this run.";
    case "regression":
      return "Regression — it had cleared in a prior run and came back.";
    case "flaky":
      return "Flaky — oscillating pass/fail across recent runs.";
    case "known":
      return "Known — ongoing from the previous run.";
    default:
      return `Status: ${status}.`;
  }
}
