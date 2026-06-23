import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { QA_FACTS, randomQaFact } from "@/lib/qaFacts";

import { LoadingFact } from "./LoadingFact";

describe("qaFacts", () => {
  it("is a curated, static set of ~15-20 one-sentence facts", () => {
    expect(QA_FACTS.length).toBeGreaterThanOrEqual(15);
    expect(QA_FACTS.length).toBeLessThanOrEqual(20);
    expect(new Set(QA_FACTS).size).toBe(QA_FACTS.length); // no duplicates
    for (const fact of QA_FACTS) {
      expect(fact.trim()).toBe(fact);
      expect(fact).not.toContain("\n"); // one short sentence, no newlines
      expect(fact.length).toBeGreaterThan(20);
    }
  });

  it("randomQaFact always returns a member of the list", () => {
    for (let i = 0; i < 50; i += 1) {
      expect(QA_FACTS).toContain(randomQaFact());
    }
  });
});

describe("LoadingFact", () => {
  it("renders exactly one curated fact", () => {
    const { container } = render(<LoadingFact />);
    expect(QA_FACTS).toContain((container.textContent ?? "").trim());
  });

  it("is decorative (hidden from assistive tech) and softly fades in", () => {
    const { container } = render(<LoadingFact />);
    const paragraph = container.querySelector("p");
    expect(paragraph?.getAttribute("aria-hidden")).toBe("true");
    expect(paragraph?.className).toContain("animate-fade-in");
    // Quiet, tertiary tone — never louder than the loading label.
    expect(paragraph?.className).toContain("text-status-neutral-solid");
  });
});
