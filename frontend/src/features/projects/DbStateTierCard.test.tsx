import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  projectApi: { getDbStateTier: vi.fn(), setDbStateTier: vi.fn() },
}));

import { projectApi } from "@/lib/api/client";

import { DbStateTierCard } from "./DbStateTierCard";

function tier(value: "off" | "read_only" | "full") {
  return { ok: true as const, status: 200, data: { project_id: "p1", tier: value } };
}

describe("DbStateTierCard", () => {
  beforeEach(() => {
    vi.mocked(projectApi.getDbStateTier).mockReset();
    vi.mocked(projectApi.setDbStateTier).mockReset();
  });

  it("shows the three tiers, the current selection, and the full-write caveat", async () => {
    vi.mocked(projectApi.getDbStateTier).mockResolvedValue(tier("read_only"));

    render(<DbStateTierCard projectId="p1" />);

    const group = await screen.findByRole("radiogroup", {
      name: "DB-state testing tier",
    });
    expect(group).toBeInTheDocument();
    // The current tier comes from the API, not a default.
    expect(screen.getByRole("radio", { name: /Read-only/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Off/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /Full/ })).not.toBeChecked();
    // The safety caveat is stated plainly, never hidden.
    expect(screen.getByText(/Full writes to the target database/)).toBeInTheDocument();
    expect(screen.getByText(/never your production data/)).toBeInTheDocument();
    expect(projectApi.getDbStateTier).toHaveBeenCalledWith("p1");
  });

  it("PUTs the new tier when a different one is chosen", async () => {
    vi.mocked(projectApi.getDbStateTier).mockResolvedValue(tier("off"));
    vi.mocked(projectApi.setDbStateTier).mockResolvedValue(tier("full"));

    render(<DbStateTierCard projectId="p1" />);
    fireEvent.click(await screen.findByRole("radio", { name: /Full/ }));

    await waitFor(() =>
      expect(projectApi.setDbStateTier).toHaveBeenCalledWith("p1", { tier: "full" }),
    );
    expect(await screen.findByText("Testing tier updated.")).toBeInTheDocument();
  });

  it("surfaces the server's 403 honestly when a change is refused", async () => {
    vi.mocked(projectApi.getDbStateTier).mockResolvedValue(tier("off"));
    vi.mocked(projectApi.setDbStateTier).mockResolvedValue({
      ok: false,
      status: 403,
      data: null,
      error: "forbidden",
    });

    render(<DbStateTierCard projectId="p1" />);
    fireEvent.click(await screen.findByRole("radio", { name: /Read-only/ }));

    expect(
      await screen.findByText(/don't have permission to change this/),
    ).toBeInTheDocument();
    // The optimistic selection rolls back to the API's tier.
    expect(screen.getByRole("radio", { name: /Off/ })).toBeChecked();
  });

  it("shows a load error if the tier can't be fetched", async () => {
    vi.mocked(projectApi.getDbStateTier).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "boom",
    });

    render(<DbStateTierCard projectId="p1" />);
    // The server's error is surfaced, not swallowed.
    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });
});
