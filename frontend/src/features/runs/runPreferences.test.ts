import { describe, expect, it } from "vitest";

import type { RunPreferences } from "@/lib/api/types";

import { runPreferencesLabel } from "./runPreferences";

function prefs(over: Partial<RunPreferences>): RunPreferences {
  return {
    mode: "mode_b",
    strategy: "full_sweep",
    layers: null,
    modules: null,
    changeset_size: null,
    layer: null,
    ...over,
  };
}

describe("runPreferencesLabel", () => {
  it("labels a full sweep", () => {
    expect(runPreferencesLabel(prefs({}))).toBe("Autonomous · full sweep");
  });

  it("labels a module-scoped run with its layers", () => {
    expect(
      runPreferencesLabel(prefs({ modules: ["orders", "users"], layers: ["api"] })),
    ).toBe("Autonomous · modules: orders, users · API");
  });

  it("labels a change-impact run with the file count", () => {
    expect(
      runPreferencesLabel(prefs({ strategy: "change_impact", changeset_size: 3 })),
    ).toBe("Autonomous · changed files (3)");
  });

  it("labels a describe-it run by its authoring engine", () => {
    expect(runPreferencesLabel(prefs({ mode: "mode_c", layer: "api" }))).toBe(
      "Describe it · API contract",
    );
    expect(runPreferencesLabel(prefs({ mode: "mode_c", layer: "ui" }))).toBe(
      "Describe it · UI journey",
    );
  });

  it("is empty when there are no preferences", () => {
    expect(runPreferencesLabel(null)).toBe("");
  });
});
