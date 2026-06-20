import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Finding } from "@/lib/api/types";

import { FindingDrawer } from "./FindingDrawer";

const richFinding: Finding = {
  id: "a",
  title: "Checkout 500",
  root_cause_key: "endpoint=POST api/orders#fail|status=500",
  layer: "api",
  severity: "critical",
  status: "regression",
  oracle_source: "rule-derived",
  explains_count: 3,
  location: { page: "/checkout", endpoints: ["POST api/orders"], tables: ["orders"] },
  expected: { assertions: [{ kind: "status" }] },
  evidence_ref: "ev/trace-123.zip",
};

const bareFinding: Finding = {
  id: "b",
  title: "Cart count drifted",
  root_cause_key: "endpoint=POST api/cart#fail",
  layer: "ui",
  severity: "minor",
  status: "new",
  oracle_source: "characterization",
  explains_count: 1,
};

describe("FindingDrawer", () => {
  it("opens from a selected finding and renders the summary + badges", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Checkout 500")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Rule-derived")).toBeInTheDocument();
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(screen.getByText("Regression")).toBeInTheDocument();
    expect(screen.getByText("explains 3 tests")).toBeInTheDocument();
  });

  it("renders nothing when no finding is selected", () => {
    render(<FindingDrawer finding={null} onClose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the cross-layer path and highlights the failing hop", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    const apiHop = screen.getByText("POST api/orders").parentElement!;
    expect(within(apiHop).getByText("failing")).toBeInTheDocument();

    const pageHop = screen.getByText("/checkout").parentElement!;
    expect(within(pageHop).queryByText("failing")).toBeNull();

    expect(screen.getByText("orders")).toBeInTheDocument();
    expect(screen.getByText(/Failing hop:/)).toBeInTheDocument();
  });

  it("flags absent fields gracefully without crashing", () => {
    render(<FindingDrawer finding={bareFinding} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/expected oracle/i)).toBeInTheDocument();
    expect(screen.getByText(/No evidence reference is exposed/i)).toBeInTheDocument();
    expect(screen.getByText(/No run-by-run timeline is exposed/i)).toBeInTheDocument();
    // Cross-layer degrades to the failing node from the key (partial).
    expect(screen.getByText("POST api/cart")).toBeInTheDocument();
    expect(screen.getByText(/showing the failing node/i)).toBeInTheDocument();
  });

  it("toggles collapsible sections", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    const header = screen.getByRole("button", { name: "Confidence" });
    expect(screen.getByText(/Rule-derived — this breaks/)).toBeInTheDocument();

    fireEvent.click(header);
    expect(screen.queryByText(/Rule-derived — this breaks/)).toBeNull();

    fireEvent.click(header);
    expect(screen.getByText(/Rule-derived — this breaks/)).toBeInTheDocument();
  });

  it("closes on Escape and moves focus to the close button on open", () => {
    const onClose = vi.fn();
    render(<FindingDrawer finding={richFinding} onClose={onClose} />);

    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("restores focus to the trigger when closed", () => {
    function Harness() {
      const [finding, setFinding] = useState<Finding | null>(null);
      return (
        <>
          <button type="button" onClick={() => setFinding(richFinding)}>
            Open
          </button>
          <FindingDrawer finding={finding} onClose={() => setFinding(null)} />
        </>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open" });
    trigger.focus();
    fireEvent.click(trigger);

    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(trigger).toHaveFocus();
  });
});
