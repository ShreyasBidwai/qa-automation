import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  adminApi: {
    me: vi.fn(),
    listOrgs: vi.fn(),
    getOrg: vi.fn(),
    suspendOrg: vi.fn(),
    reactivateOrg: vi.fn(),
    orgUsage: vi.fn(),
    setOrgPlan: vi.fn(),
  },
  planApi: { list: vi.fn() },
}));

import { adminApi, planApi } from "@/lib/api/client";
import type {
  AdminMe,
  AdminOrgDetail,
  AdminOrgListItem,
  PlanItem,
} from "@/lib/api/types";
import { setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";

import { AdminTenantsPage } from "./AdminTenantsPage";

function staff(permissions: string[]): AdminMe {
  return { user_id: "s1", email: "ops@x.dev", staff_role: "superadmin", permissions };
}

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

function org(over: Partial<AdminOrgListItem> = {}): AdminOrgListItem {
  return {
    id: "o1",
    name: "Acme Corp",
    is_personal: false,
    suspended: false,
    member_count: 4,
    project_count: 2,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function detail(over: Partial<AdminOrgDetail> = {}): AdminOrgDetail {
  return {
    id: "o1",
    name: "Acme Corp",
    is_personal: false,
    suspended: false,
    member_count: 4,
    project_count: 2,
    created_at: "2026-01-01T00:00:00Z",
    plan_key: "free",
    members: [{ user_id: "u1", email: "a@x.dev", name: "Ann", role: "owner" }],
    ...over,
  };
}

function okList(items: AdminOrgListItem[], total: number) {
  return { ok: true, status: 200, data: { items, total, limit: 25, offset: 0 } };
}

describe("AdminTenantsPage", () => {
  beforeEach(() => {
    resetStaffCache();
    setToken("staff-token");
    vi.mocked(adminApi.me).mockReset();
    vi.mocked(adminApi.listOrgs).mockReset();
    vi.mocked(adminApi.getOrg).mockReset();
    vi.mocked(adminApi.suspendOrg).mockReset();
    vi.mocked(adminApi.orgUsage).mockReset();
    vi.mocked(adminApi.setOrgPlan).mockReset();
    vi.mocked(planApi.list).mockReset();
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: staff(["view_tenants", "manage_tenants"]),
    });
  });

  it("renders tenants from the list endpoint", async () => {
    vi.mocked(adminApi.listOrgs).mockResolvedValue(
      okList(
        [org({ id: "a", name: "Alpha Inc" }), org({ id: "b", name: "Beta LLC" })],
        2,
      ),
    );

    render(<AdminTenantsPage />);

    expect(await screen.findByText("Alpha Inc")).toBeInTheDocument();
    expect(screen.getByText("Beta LLC")).toBeInTheDocument();
    await waitFor(() =>
      expect(adminApi.listOrgs).toHaveBeenCalledWith({
        search: "",
        limit: 25,
        offset: 0,
      }),
    );
  });

  it("suspends an org from the detail drawer (manage_tenants)", async () => {
    vi.mocked(adminApi.listOrgs).mockResolvedValue(okList([org()], 1));
    vi.mocked(adminApi.getOrg).mockResolvedValue({
      ok: true,
      status: 200,
      data: detail({ suspended: false }),
    });
    vi.mocked(adminApi.suspendOrg).mockResolvedValue({
      ok: true,
      status: 200,
      data: detail({ suspended: true }),
    });

    render(<AdminTenantsPage />);

    // Open the drawer for the org's row.
    fireEvent.click(await screen.findByText("Acme Corp"));

    const suspend = await screen.findByRole("button", {
      name: "Suspend organization",
    });
    fireEvent.click(suspend);

    await waitFor(() => expect(adminApi.suspendOrg).toHaveBeenCalledWith("o1"));
  });

  it("hides management actions without manage_tenants", async () => {
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: staff(["view_tenants"]), // view only
    });
    vi.mocked(adminApi.listOrgs).mockResolvedValue(okList([org()], 1));
    vi.mocked(adminApi.getOrg).mockResolvedValue({
      ok: true,
      status: 200,
      data: detail({ suspended: false }),
    });

    render(<AdminTenantsPage />);
    fireEvent.click(await screen.findByText("Acme Corp"));

    // The members list confirms the drawer opened; the suspend action is absent.
    expect(await screen.findByText("Members")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend organization" })).toBeNull();
  });

  it("changes an org's plan from the drawer (manage_billing)", async () => {
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: staff(["view_tenants", "manage_billing"]),
    });
    vi.mocked(adminApi.listOrgs).mockResolvedValue(okList([org()], 1));
    vi.mocked(adminApi.getOrg).mockResolvedValue({
      ok: true,
      status: 200,
      data: detail({ plan_key: "free" }),
    });
    vi.mocked(planApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [plan(), plan({ key: "team", name: "Team" })] },
    });
    vi.mocked(adminApi.setOrgPlan).mockResolvedValue({
      ok: true,
      status: 200,
      data: detail({ plan_key: "team" }),
    });

    render(<AdminTenantsPage />);
    fireEvent.click(await screen.findByText("Acme Corp"));

    const select = await screen.findByLabelText("Assign plan");
    fireEvent.change(select, { target: { value: "team" } });

    await waitFor(() => expect(adminApi.setOrgPlan).toHaveBeenCalledWith("o1", "team"));
  });

  it("hides the plan selector without manage_billing", async () => {
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: staff(["view_tenants"]), // no billing perms
    });
    vi.mocked(adminApi.listOrgs).mockResolvedValue(okList([org()], 1));
    vi.mocked(adminApi.getOrg).mockResolvedValue({
      ok: true,
      status: 200,
      data: detail({ plan_key: "free" }),
    });

    render(<AdminTenantsPage />);
    fireEvent.click(await screen.findByText("Acme Corp"));

    // The drawer opened (members show) but the plan selector is gated away.
    expect(await screen.findByText("Members")).toBeInTheDocument();
    expect(screen.queryByLabelText("Assign plan")).toBeNull();
    expect(planApi.list).not.toHaveBeenCalled();
  });
});
