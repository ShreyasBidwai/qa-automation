import { cn } from "@/lib/utils";

import { TRUST_VIZ, trustTier, type TrustTier } from "./trustTier";

/**
 * The oracle-trust mark — Polaris's one signature device (design brief). It makes
 * "how much should I believe this test" visible at a glance, by oracle tier:
 *
 *   ● rule-derived     solid emerald  — strong, follows a real rule
 *   ◌ characterization hollow amber   — weak, only pins current behaviour
 *   ◉ spec-grounded    blue ring+core — anchored to a documented contract
 *
 * Colour is never the only signal: the tier name always travels with the glyph
 * (visible as a label, or sr-only when the glyph stands alone), so it reads for
 * colour-blind and screen-reader users too.
 */

/** The bare glyph (●/◌/◉). Decorative — the name is carried by the caller. */
export function TrustGlyph({ tier }: { tier: TrustTier }) {
  if (tier === "spec") {
    // ◉ — ring + core (a documented contract: anchored).
    return (
      <span
        aria-hidden="true"
        className="flex h-[9px] w-[9px] shrink-0 items-center justify-center rounded-full border-2 border-trust-spec-solid"
      >
        <span className="h-[3px] w-[3px] rounded-full bg-trust-spec-solid" />
      </span>
    );
  }
  if (tier === "char") {
    // ◌ — hollow ring (only pins current behaviour: weak).
    return (
      <span
        aria-hidden="true"
        className="h-[9px] w-[9px] shrink-0 rounded-full border-2 border-trust-char-solid bg-transparent"
      />
    );
  }
  if (tier === "rule") {
    // ● — solid disc (follows a real rule: strong).
    return (
      <span
        aria-hidden="true"
        className="h-[9px] w-[9px] shrink-0 rounded-full bg-trust-rule-solid"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="h-[9px] w-[9px] shrink-0 rounded-full bg-status-neutral-solid"
    />
  );
}

export function TrustMark({
  source,
  label = false,
  pill = false,
  className,
}: {
  /** The finding/evidence `oracle_source` (e.g. "rule-derived"). */
  source: string;
  /** Show the tier name beside the glyph (always shown when `pill`). */
  label?: boolean;
  /** Wrap glyph + name in a bordered chip (used in the evidence list). */
  pill?: boolean;
  className?: string;
}) {
  const viz = TRUST_VIZ[trustTier(source)];
  // For an unrecognized source, keep the raw value as the label so we never hide data.
  const name = viz.tier === "unknown" ? source : viz.name;

  if (pill) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[10.5px]",
          viz.pill,
          className,
        )}
      >
        <TrustGlyph tier={viz.tier} />
        {name}
      </span>
    );
  }

  if (label) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 font-mono text-[10.5px]",
          viz.text,
          className,
        )}
      >
        <TrustGlyph tier={viz.tier} />
        {name}
      </span>
    );
  }

  // Glyph only — keep the name available to assistive tech.
  return (
    <span className={cn("inline-flex items-center", className)}>
      <TrustGlyph tier={viz.tier} />
      <span className="sr-only">{name}</span>
    </span>
  );
}
