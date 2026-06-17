import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the data layer so the component test is deterministic and offline
// (Standards §15: isolated, no network).
vi.mock("@/lib/api/client", () => ({
  healthApi: {
    liveness: vi.fn(),
    readiness: vi.fn(),
  },
}));

import { healthApi } from "@/lib/api/client";

import { SystemStatusPage } from "./SystemStatusPage";

describe("SystemStatusPage", () => {
  beforeEach(() => {
    vi.mocked(healthApi.liveness).mockResolvedValue({
      ok: true,
      status: 200,
      data: { status: "ok" },
    });
    vi.mocked(healthApi.readiness).mockResolvedValue({
      ok: true,
      status: 200,
      data: { status: "ready", checks: { database: "up" } },
    });
  });

  it("renders backend and database as healthy once checks resolve", async () => {
    render(<SystemStatusPage />);

    expect(
      screen.getByRole("heading", { name: "System status" }),
    ).toBeInTheDocument();
    // findBy* waits for the async health checks to resolve — no sleeps.
    expect(await screen.findByText("Operational")).toBeInTheDocument();
    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(
      await screen.findByText("All systems operational"),
    ).toBeInTheDocument();
  });

  it("shows the backend as unreachable when the API cannot be reached", async () => {
    vi.mocked(healthApi.liveness).mockResolvedValue({
      ok: false,
      status: 0,
      data: null,
    });
    vi.mocked(healthApi.readiness).mockResolvedValue({
      ok: false,
      status: 0,
      data: null,
    });

    render(<SystemStatusPage />);

    expect(await screen.findByText("Unreachable")).toBeInTheDocument();
    expect(await screen.findByText("Degraded")).toBeInTheDocument();
  });
});
