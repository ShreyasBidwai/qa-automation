import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Finding } from "@/lib/api/types";

import { BlastPathRibbon } from "./BlastPathRibbon";

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f1",
    root_cause_key: "k",
    title: "t",
    layer: "api",
    severity: "major",
    status: "new",
    oracle_source: "rule-derived",
    explains_count: 1,
    ...over,
  };
}

describe("BlastPathRibbon", () => {
  it("renders the full page → endpoint → table chain and marks the failing node", () => {
    render(
      <BlastPathRibbon
        finding={finding({
          root_cause_key: "endpoint=POST api/orders#fail|status=500",
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
        })}
      />,
    );

    expect(screen.getByText("/checkout")).toBeInTheDocument();
    expect(screen.getByText("POST api/orders")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
    // Node type captions.
    expect(screen.getByText("page")).toBeInTheDocument();
    expect(screen.getByText("endpoint")).toBeInTheDocument();
    expect(screen.getByText("table")).toBeInTheDocument();

    const failingNode = screen.getByText("failing here").closest("div")!;
    expect(within(failingNode).getByText("POST api/orders")).toBeInTheDocument();
  });

  it("degrades to the failing node alone when the path can't be resolved", () => {
    render(
      <BlastPathRibbon
        finding={finding({ root_cause_key: "endpoint=POST api/cart#fail" })}
      />,
    );

    expect(screen.getByText("POST api/cart")).toBeInTheDocument();
    expect(screen.getByText(/showing the failing node/i)).toBeInTheDocument();
  });

  it("says so when no cross-layer location can be resolved", () => {
    render(<BlastPathRibbon finding={finding({ root_cause_key: "opaque-key" })} />);
    expect(screen.getByText(/resolved for this finding/i)).toBeInTheDocument();
  });
});
