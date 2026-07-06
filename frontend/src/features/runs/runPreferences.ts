import type { RunPreferences } from "@/lib/api/types";

/**
 * A short, human label for a run's preferences (ADR-0062) — so recent runs are
 * distinguishable at a glance ("Autonomous · modules: orders · API, UI"). Deterministic,
 * pure. Prompt text is never included (the backend doesn't expose it).
 */
export function runPreferencesLabel(
  preferences: RunPreferences | null | undefined,
): string {
  if (!preferences) return "";

  if (preferences.mode === "mode_c") {
    const engine = preferences.layer === "api" ? "API contract" : "UI journey";
    return `Describe it · ${engine}`;
  }

  // Autonomous (mode_b): scope, then the layer subset (omitted = all layers).
  const parts = ["Autonomous"];
  if (preferences.modules && preferences.modules.length > 0) {
    parts.push(`modules: ${preferences.modules.join(", ")}`);
  } else if (preferences.strategy === "change_impact") {
    const n = preferences.changeset_size;
    parts.push(n ? `changed files (${n})` : "changed files");
  } else {
    parts.push("full sweep");
  }
  if (preferences.layers && preferences.layers.length > 0) {
    parts.push(preferences.layers.map((layer) => layer.toUpperCase()).join(", "));
  }
  return parts.join(" · ");
}
