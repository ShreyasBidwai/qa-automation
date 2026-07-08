import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  adminApi: { me: vi.fn(), generationQuality: vi.fn() },
}));

import { adminApi } from "@/lib/api/client";
import type { AdminMe, GenerationQuality } from "@/lib/api/types";
import { setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";

import { AdminFlywheelPage } from "./AdminFlywheelPage";

function staff(permissions: string[]): AdminMe {
  return { user_id: "s1", email: "ops@x.dev", staff_role: "superadmin", permissions };
}

function quality(over: Partial<GenerationQuality> = {}): GenerationQuality {
  return {
    since_days: 30,
    prompt_version: null,
    total: 100,
    by_outcome: { pass: 70, fail: 15, error: 10, skipped: 5 },
    repaired: 8,
    healed: 4,
    flaky: 3,
    triaged: 20,
    triage_rejected: 5,
    ...over,
  };
}

function ok<T>(data: T) {
  return { ok: true, status: 200, data };
}

describe("AdminFlywheelPage", () => {
  beforeEach(() => {
    resetStaffCache();
    setToken("staff-token");
    vi.mocked(adminApi.me).mockReset();
    vi.mocked(adminApi.generationQuality).mockReset();
    vi.mocked(adminApi.me).mockResolvedValue(ok(staff(["view_ops"])));
  });

  it("renders the composite index, tiles, and the outcome mix", async () => {
    vi.mocked(adminApi.generationQuality).mockResolvedValue(ok(quality()));

    render(<AdminFlywheelPage />);

    expect(await screen.findByText("Generation quality index")).toBeInTheDocument();
    expect(screen.getByText("Total signals")).toBeInTheDocument();
    expect(screen.getByText("Outcome mix")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    // pass-without-repair = (70 - 8) / 100 = 62%.
    expect(screen.getByText("62%")).toBeInTheDocument();
    // false-positive = triage_rejected / triaged = 5 / 20 = 25%.
    expect(screen.getByText("25%")).toBeInTheDocument();

    // Defaults to the 30-day window.
    await waitFor(() => expect(adminApi.generationQuality).toHaveBeenCalledWith(30));
  });

  it("shows the honest empty state when there are no signals", async () => {
    vi.mocked(adminApi.generationQuality).mockResolvedValue(
      ok(
        quality({
          total: 0,
          by_outcome: {},
          repaired: 0,
          healed: 0,
          flaky: 0,
          triaged: 0,
          triage_rejected: 0,
        }),
      ),
    );

    render(<AdminFlywheelPage />);

    expect(await screen.findByText("No generation signals yet")).toBeInTheDocument();
  });
});
