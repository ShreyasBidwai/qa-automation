import { describe, expect, it } from "vitest";

import { HELP_SECTIONS } from "./helpContent";

describe("HELP_SECTIONS", () => {
  it("covers all 11 documented sections", () => {
    expect(HELP_SECTIONS).toHaveLength(11);
  });

  it("has unique, non-empty ids and titles", () => {
    const ids = HELP_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const section of HELP_SECTIONS) {
      expect(section.id).toMatch(/\S/);
      expect(section.title).toMatch(/\S/);
      expect(section.summary).toMatch(/\S/);
    }
  });

  it("gives every section at least one concrete example (beginner-proof brief)", () => {
    for (const section of HELP_SECTIONS) {
      const hasExample = section.body.some((block) => block.kind === "example");
      expect(hasExample, `section "${section.id}" needs an example block`).toBe(true);
    }
  });

  it("defines the three trust marks with distinct symbols, colours, and variants", () => {
    const section = HELP_SECTIONS.find((s) => s.id === "trust-marks");
    const block = section?.body.find((b) => b.kind === "trustMarks");
    expect(block).toBeDefined();
    if (block?.kind !== "trustMarks") throw new Error("expected a trustMarks block");

    expect(block.items).toHaveLength(3);
    expect(block.items.map((m) => m.variant)).toEqual(["solid", "hollow", "ring"]);
    expect(block.items.map((m) => m.color)).toEqual(["emerald", "amber", "blue"]);
    expect(block.items.map((m) => m.name)).toEqual([
      "Rule-derived",
      "Characterization",
      "Spec-grounded",
    ]);
    // Each symbol is distinct.
    expect(new Set(block.items.map((m) => m.symbol)).size).toBe(3);
  });

  it("draws the blast path as a 4-node chain with a valid failing node", () => {
    const section = HELP_SECTIONS.find((s) => s.id === "blast-path");
    const block = section?.body.find((b) => b.kind === "blastPath");
    if (block?.kind !== "blastPath") throw new Error("expected a blastPath block");

    expect(block.nodes.map((n) => n.tier)).toEqual([
      "Page",
      "Endpoint",
      "Model",
      "Table",
    ]);
    expect(block.failingIndex).toBeGreaterThanOrEqual(0);
    expect(block.failingIndex).toBeLessThan(block.nodes.length);
  });

  it("defines every glossary term the brief requires", () => {
    const glossary = HELP_SECTIONS.find((s) => s.id === "glossary");
    const block = glossary?.body.find((b) => b.kind === "definitions");
    if (block?.kind !== "definitions") throw new Error("expected a definitions block");

    const terms = block.items.map((d) => d.term.toLowerCase());
    for (const required of [
      "finding",
      "oracle",
      "trust mark",
      "blast path",
      "mode",
      "scope",
      "the brain",
      "crawl",
      "run",
      "severity",
      "confidence",
      "triage",
    ]) {
      expect(terms, `glossary must define "${required}"`).toContain(required);
    }
  });
});
