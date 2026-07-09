import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeltaBadge } from "./DeltaBadge";

describe("DeltaBadge", () => {
  it("shows an upward delta in the pass tone", () => {
    render(<DeltaBadge delta={{ points: 5, direction: "up" }} label="vs prior" />);
    expect(screen.getByText("5% vs prior")).toHaveClass("text-status-pass-fg");
  });

  it("shows a downward delta in the fail tone, with an absolute value", () => {
    render(<DeltaBadge delta={{ points: -7, direction: "down" }} label="vs 30D ago" />);
    expect(screen.getByText("7% vs 30D ago")).toHaveClass("text-status-fail-fg");
  });

  it("renders a quiet 'no change' for a flat delta, ignoring the label", () => {
    render(<DeltaBadge delta={{ points: 0, direction: "flat" }} label="vs prior" />);
    expect(screen.getByText("no change")).toBeInTheDocument();
    expect(screen.queryByText(/vs prior/)).toBeNull();
  });
});
