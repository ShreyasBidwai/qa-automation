import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrustMark } from "./TrustMark";
import { trustTier } from "./trustTier";

describe("trustTier", () => {
  it("maps an oracle_source to its tier", () => {
    expect(trustTier("rule-derived")).toBe("rule");
    expect(trustTier("characterization")).toBe("char");
    expect(trustTier("spec-grounded")).toBe("spec");
    expect(trustTier("something-else")).toBe("unknown");
  });
});

describe("TrustMark", () => {
  it("shows the tier name as an inline label", () => {
    render(<TrustMark source="rule-derived" label />);
    expect(screen.getByText("rule-derived")).toBeInTheDocument();
  });

  it("renders a pill in the tier palette", () => {
    render(<TrustMark source="characterization" pill />);
    expect(screen.getByText("characterization")).toHaveClass("bg-trust-char-bg");
  });

  it("keeps the name available to assistive tech when the glyph stands alone", () => {
    render(<TrustMark source="spec-grounded" />);
    // The visible glyph is decorative; the tier name is rendered sr-only.
    expect(screen.getByText("spec-grounded")).toHaveClass("sr-only");
  });

  it("falls back to the raw source for an unknown tier (never hides data)", () => {
    render(<TrustMark source="mystery-oracle" label />);
    expect(screen.getByText("mystery-oracle")).toBeInTheDocument();
  });
});
