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
  confidence_mixed: true,
  location: {
    anchor: {
      node_type: "endpoint",
      identifier: "POST api/orders",
      label: "POST api/orders",
    },
    page: "/checkout",
    endpoints: ["POST api/orders"],
    tables: ["orders"],
  },
  expected: { assertions: [{ kind: "status" }] },
  evidence: [
    {
      summary: "Failed — expected status 500; checks status",
      oracle_source: "rule-derived",
      reference: "ev/trace-1.zip",
    },
    { summary: "Failed — checks body", oracle_source: "characterization", reference: null },
    {
      summary: "Errored — no recorded expectation",
      oracle_source: "spec-grounded",
      reference: null,
    },
  ],
  history: {
    classification: "regression",
    occurrence_count: 3,
    first_seen_run: "11111111-1111-1111-1111-111111111111",
    last_seen_run: "22222222-2222-2222-2222-222222222222",
  },
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
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(screen.getByText("Regression")).toBeInTheDocument();
    expect(screen.getByText("explains 3 tests")).toBeInTheDocument();
  });

  it("renders nothing when no finding is selected", () => {
    render(<FindingDrawer finding={null} onClose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the location anchor (the deepest failing node)", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    expect(screen.getByText(/Failing node:/)).toBeInTheDocument();
    expect(screen.getByText("(endpoint)")).toBeInTheDocument();
  });

  it("renders the full cross-layer ribbon and highlights the failing hop", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    // All three tiers are present (UI page, API endpoint, DB table).
    expect(screen.getByText("/checkout")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
    // The failing hop is the API anchor (from the key), not the page.
    const failingHop = screen.getByText("failing").parentElement!;
    expect(within(failingHop).getByText("POST api/orders")).toBeInTheDocument();
    expect(screen.getByText(/Failing hop:/)).toBeInTheDocument();
  });

  it("renders the evidence list with a trust badge per failing assertion", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    // rule-derived → emerald (pass)
    const ruleItem = screen
      .getByText("Failed — expected status 500; checks status")
      .closest("li")!;
    expect(within(ruleItem).getByText("Rule-derived")).toHaveClass("bg-status-pass-bg");
    expect(within(ruleItem).getByText("ev/trace-1.zip")).toBeInTheDocument();

    // characterization → amber (flaky)
    const charItem = screen.getByText("Failed — checks body").closest("li")!;
    expect(within(charItem).getByText("Characterization")).toHaveClass(
      "bg-status-flaky-bg",
    );

    // spec-grounded → blue (info)
    const specItem = screen
      .getByText("Errored — no recorded expectation")
      .closest("li")!;
    expect(within(specItem).getByText("Spec-grounded")).toHaveClass("bg-status-info-bg");
  });

  it("renders the history classification and occurrence count", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    expect(screen.getByText(/Regression — it had cleared/)).toBeInTheDocument();
    expect(screen.getByText(/seen in 3 runs/)).toBeInTheDocument();
    expect(
      screen.getByText("11111111-1111-1111-1111-111111111111"),
    ).toBeInTheDocument();
  });

  it("does not show any 'not exposed yet' flags for the now-exposed fields", () => {
    render(<FindingDrawer finding={richFinding} onClose={vi.fn()} />);

    expect(screen.queryByText(/exposed/i)).toBeNull();
    expect(screen.queryByText(/run-by-run timeline/i)).toBeNull();
  });

  it("degrades gracefully when detail fields are absent, without stale flags", () => {
    render(<FindingDrawer finding={bareFinding} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // Ribbon still degrades to the failing node parsed from the key.
    expect(screen.getByText("POST api/cart")).toBeInTheDocument();
    expect(screen.getByText(/showing the failing node/i)).toBeInTheDocument();
    // Evidence + history degrade with plain language, not "not exposed yet".
    expect(screen.getByText(/No failing assertions are recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/first seen in this run/i)).toBeInTheDocument();
    expect(screen.queryByText(/exposed/i)).toBeNull();
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
