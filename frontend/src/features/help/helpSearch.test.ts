import { describe, expect, it } from "vitest";

import { HELP_SECTIONS, type HelpSection } from "./helpContent";
import {
  blockText,
  queryTokens,
  searchSections,
  sectionSearchText,
} from "./helpSearch";

function section(over: Partial<HelpSection>): HelpSection {
  return {
    id: "s",
    title: "Title",
    summary: "Summary",
    body: [],
    ...over,
  };
}

describe("blockText", () => {
  it("flattens each block kind to its words", () => {
    expect(blockText({ kind: "text", text: "hello world" })).toBe("hello world");
    expect(blockText({ kind: "example", text: "an example" })).toBe("an example");
    expect(blockText({ kind: "list", items: ["a", "b"] })).toBe("a b");
    expect(
      blockText({ kind: "steps", items: [{ label: "Run", detail: "executes" }] }),
    ).toBe("Run executes");
    expect(
      blockText({
        kind: "definitions",
        items: [{ term: "Scope", definition: "layers" }],
      }),
    ).toBe("Scope layers");
    expect(
      blockText({
        kind: "trustMarks",
        items: [
          {
            variant: "solid",
            symbol: "●",
            color: "emerald",
            name: "Rule-derived",
            strength: "strong",
            meaning: "trust it",
          },
        ],
      }),
    ).toContain("emerald");
    expect(
      blockText({
        kind: "blastPath",
        nodes: [{ tier: "Page", label: "/checkout" }],
        failingIndex: 0,
        caption: "lit here",
      }),
    ).toBe("Page /checkout lit here");
  });
});

describe("sectionSearchText", () => {
  it("indexes title, summary, keywords, and body text together", () => {
    const text = sectionSearchText(
      section({
        title: "Trust marks",
        summary: "the symbols",
        keywords: ["◉", "spec-grounded"],
        body: [{ kind: "text", text: "Behind every test is an oracle" }],
      }),
    );
    expect(text).toContain("trust marks");
    expect(text).toContain("the symbols");
    expect(text).toContain("◉");
    expect(text).toContain("oracle");
  });

  it("lowercases so matching is case-insensitive", () => {
    expect(sectionSearchText(section({ title: "CHECKOUT" }))).toContain("checkout");
  });
});

describe("queryTokens", () => {
  it("splits on whitespace and drops empties", () => {
    expect(queryTokens("  trust   amber ")).toEqual(["trust", "amber"]);
    expect(queryTokens("")).toEqual([]);
    expect(queryTokens("   ")).toEqual([]);
  });
});

describe("searchSections", () => {
  const sections = [
    section({
      id: "a",
      title: "Trust marks",
      body: [{ kind: "text", text: "amber and emerald" }],
    }),
    section({
      id: "b",
      title: "Run scope",
      body: [{ kind: "text", text: "api ui full" }],
    }),
    section({ id: "c", title: "Findings", keywords: ["ranked problem"], body: [] }),
  ];

  it("returns all sections for an empty or whitespace query", () => {
    expect(searchSections(sections, "")).toHaveLength(3);
    expect(searchSections(sections, "   ")).toHaveLength(3);
  });

  it("matches on the title", () => {
    expect(searchSections(sections, "scope").map((s) => s.id)).toEqual(["b"]);
  });

  it("matches on body text the title does not contain", () => {
    expect(searchSections(sections, "emerald").map((s) => s.id)).toEqual(["a"]);
  });

  it("matches on keywords", () => {
    expect(searchSections(sections, "ranked").map((s) => s.id)).toEqual(["c"]);
  });

  it("requires every token to be present (AND), in any order", () => {
    expect(searchSections(sections, "amber trust").map((s) => s.id)).toEqual(["a"]);
    expect(searchSections(sections, "amber scope")).toHaveLength(0);
  });

  it("is case-insensitive", () => {
    expect(searchSections(sections, "TRUST").map((s) => s.id)).toEqual(["a"]);
  });

  it("returns nothing when no section matches", () => {
    expect(searchSections(sections, "nonexistent")).toHaveLength(0);
  });

  it("finds a section by a word unique to its body, over the real content", () => {
    // "characterization" appears only in the trust-marks section.
    const hits = searchSections(HELP_SECTIONS, "characterization");
    expect(hits).toHaveLength(1);
    expect(hits[0].id).toBe("trust-marks");
  });
});
