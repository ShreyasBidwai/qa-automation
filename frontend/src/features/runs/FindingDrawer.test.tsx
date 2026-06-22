import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ runApi: { triage: vi.fn() } }));

import { runApi } from "@/lib/api/client";
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
    {
      summary: "Failed — checks body",
      oracle_source: "characterization",
      reference: null,
    },
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
  beforeEach(() => vi.mocked(runApi.triage).mockReset());

  it("opens from a selected finding and renders the header + field grid", () => {
    render(<FindingDrawer finding={richFinding} runId="r1" onClose={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Checkout 500")).toBeInTheDocument();
    // Severity shows in both the header pill and the field grid.
    expect(screen.getAllByText("Critical").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("api")).toBeInTheDocument(); // layer field
    expect(screen.getByText("explains 3 tests")).toBeInTheDocument();
  });

  it("renders nothing when no finding is selected", () => {
    render(<FindingDrawer finding={null} runId="r1" onClose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the blast-path ribbon and marks the failing node", () => {
    render(<FindingDrawer finding={richFinding} runId="r1" onClose={vi.fn()} />);

    expect(screen.getByText("/checkout")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();

    const failingNode = screen.getByText("failing here").closest("div")!;
    expect(within(failingNode).getByText("POST api/orders")).toBeInTheDocument();
  });

  it("renders each failing assertion with its trust mark", () => {
    render(<FindingDrawer finding={richFinding} runId="r1" onClose={vi.fn()} />);

    const ruleItem = screen
      .getByText("Failed — expected status 500; checks status")
      .closest("li")!;
    expect(within(ruleItem).getByText("rule-derived")).toHaveClass("bg-trust-rule-bg");

    const charItem = screen.getByText("Failed — checks body").closest("li")!;
    expect(within(charItem).getByText("characterization")).toHaveClass(
      "bg-trust-char-bg",
    );

    const specItem = screen
      .getByText("Errored — no recorded expectation")
      .closest("li")!;
    expect(within(specItem).getByText("spec-grounded")).toHaveClass("bg-trust-spec-bg");

    // The finding-level evidence reference is still surfaced.
    expect(screen.getByText("ev/trace-123.zip")).toBeInTheDocument();
  });

  it("renders the history classification and occurrence count", () => {
    render(<FindingDrawer finding={richFinding} runId="r1" onClose={vi.fn()} />);

    expect(screen.getByText(/Regression — it had cleared/)).toBeInTheDocument();
    expect(screen.getByText(/Seen in 3 runs/)).toBeInTheDocument();
    expect(
      screen.getByText("11111111-1111-1111-1111-111111111111"),
    ).toBeInTheDocument();
  });

  it("does not show any 'not exposed yet' flags for the now-exposed fields", () => {
    render(<FindingDrawer finding={richFinding} runId="r1" onClose={vi.fn()} />);

    expect(screen.queryByText(/exposed/i)).toBeNull();
    expect(screen.queryByText(/run-by-run timeline/i)).toBeNull();
  });

  it("degrades gracefully when detail fields are absent, without stale flags", () => {
    render(<FindingDrawer finding={bareFinding} runId="r1" onClose={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("POST api/cart")).toBeInTheDocument();
    expect(screen.getByText(/showing the failing node/i)).toBeInTheDocument();
    expect(screen.getByText(/No failing assertions are recorded/i)).toBeInTheDocument();
    expect(screen.getByText(/first seen in this run/i)).toBeInTheDocument();
    expect(screen.queryByText(/exposed/i)).toBeNull();
  });

  // --- triage actions (ADR-0027) -------------------------------------------

  it("fires a triage PATCH with the note and reflects the disposition", async () => {
    const updated: Finding = {
      ...richFinding,
      triage: {
        status: "wont_fix",
        note: "dup of #12",
        triaged_at: "2026-06-20T10:00:00Z",
      },
    };
    vi.mocked(runApi.triage).mockResolvedValue({
      ok: true,
      status: 200,
      data: updated,
    });
    const onTriaged = vi.fn();

    render(
      <FindingDrawer
        finding={richFinding}
        runId="r99"
        onClose={vi.fn()}
        onTriaged={onTriaged}
      />,
    );

    fireEvent.change(screen.getByLabelText("Note (optional)"), {
      target: { value: "dup of #12" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Won't fix" }));

    await waitFor(() =>
      expect(runApi.triage).toHaveBeenCalledWith("r99", "a", {
        status: "wont_fix",
        note: "dup of #12",
      }),
    );
    // Reflects the saved disposition (button active + triaged_at shown).
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Won't fix" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.getByText(/Triaged/)).toBeInTheDocument();
    expect(onTriaged).toHaveBeenCalledWith(updated);
  });

  it("shows the current disposition + triaged_at for an already-triaged finding", () => {
    const triaged: Finding = {
      ...richFinding,
      triage: {
        status: "acknowledged",
        note: null,
        triaged_at: "2026-06-20T10:00:00Z",
      },
    };
    render(<FindingDrawer finding={triaged} runId="r1" onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Acknowledge" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/Triaged/)).toBeInTheDocument();
  });

  it("surfaces an error when the triage PATCH fails", async () => {
    vi.mocked(runApi.triage).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "Server boom",
    });

    render(<FindingDrawer finding={richFinding} runId="r1" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Resolved" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Server boom");
  });

  it("closes on Escape and moves focus to the close button on open", () => {
    const onClose = vi.fn();
    render(<FindingDrawer finding={richFinding} runId="r1" onClose={onClose} />);

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
          <FindingDrawer
            finding={finding}
            runId="r1"
            onClose={() => setFinding(null)}
          />
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
