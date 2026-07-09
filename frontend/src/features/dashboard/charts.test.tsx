import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DonutChart, LegendDot, TrendArea } from "./charts";

describe("DonutChart", () => {
  it("draws one arc per non-zero segment and renders the center", () => {
    const { container } = render(
      <DonutChart
        segments={[
          { key: "a", label: "passed", value: 3, colorClass: "text-status-pass-solid" },
          { key: "b", label: "failed", value: 1, colorClass: "text-status-fail-solid" },
          {
            key: "c",
            label: "zero",
            value: 0,
            colorClass: "text-status-neutral-solid",
          },
        ]}
        center={<span>4</span>}
      />,
    );
    // The track ring + two arcs (the zero segment is skipped).
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("shows only the empty track ring when everything is zero", () => {
    const { container } = render(
      <DonutChart
        segments={[
          { key: "a", label: "passed", value: 0, colorClass: "text-status-pass-solid" },
        ]}
      />,
    );
    expect(container.querySelectorAll("circle")).toHaveLength(1); // track only
  });
});

describe("TrendArea", () => {
  it("breaks the line at null gaps (no interpolation across missing days)", () => {
    const { container } = render(
      <TrendArea
        points={[
          { label: "d1", value: 0.9 },
          { label: "d2", value: null }, // a gap
          { label: "d3", value: 0.8 },
          { label: "d4", value: 0.85 },
        ]}
      />,
    );
    // Two separate line paths (one before the gap, one after) — not a single bridged line.
    const lines = [...container.querySelectorAll("path")].filter(
      (p) => p.getAttribute("fill") === "none",
    );
    expect(lines).toHaveLength(2);
  });
});

describe("LegendDot", () => {
  it("renders the count and label", () => {
    render(<LegendDot colorClass="bg-status-pass-solid" count={7} label="passed" />);
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("passed")).toBeInTheDocument();
  });
});
