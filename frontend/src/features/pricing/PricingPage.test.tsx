import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  planApi: { list: vi.fn() },
}));

import { planApi } from "@/lib/api/client";
import type { PlanItem } from "@/lib/api/types";

import { PricingPage } from "./PricingPage";

function plan(over: Partial<PlanItem> = {}): PlanItem {
  return {
    key: "free",
    name: "Free",
    price_per_seat_monthly_usd: 0,
    included_run_credits_monthly: 50,
    max_projects: 1,
    max_seats: 2,
    max_parallelism: 1,
    retention_days: 7,
    features: {},
    ...over,
  };
}

describe("PricingPage", () => {
  beforeEach(() => {
    vi.mocked(planApi.list).mockReset();
  });

  it("renders a card per tier with prices, quotas, and features", async () => {
    vi.mocked(planApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        items: [
          plan(),
          plan({
            key: "team",
            name: "Team",
            price_per_seat_monthly_usd: 49,
            included_run_credits_monthly: 1000,
            features: { sso: true, priority_support: true },
          }),
          plan({
            key: "enterprise",
            name: "Enterprise",
            price_per_seat_monthly_usd: null, // custom / contact us
            included_run_credits_monthly: null, // unlimited
            max_projects: null,
            max_seats: null,
          }),
        ],
      },
    });

    render(<PricingPage />);

    // Every tier's name renders.
    expect(await screen.findByText("Free")).toBeInTheDocument();
    expect(screen.getByText("Team")).toBeInTheDocument();
    expect(screen.getByText("Enterprise")).toBeInTheDocument();

    // Prices: a real per-seat number, and "Custom" for the null-priced tier.
    expect(screen.getByText("$49")).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();

    // Quotas: a formatted number and "Unlimited" for the nulls.
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getAllByText("Unlimited").length).toBeGreaterThan(0);

    // Feature flags are humanized into bullets.
    expect(screen.getByText("SSO")).toBeInTheDocument();
    expect(screen.getByText("Priority support")).toBeInTheDocument();
  });

  it("shows an empty state when the catalog is empty", async () => {
    vi.mocked(planApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [] },
    });

    render(<PricingPage />);

    expect(await screen.findByText("No plans published yet")).toBeInTheDocument();
  });
});
