import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  adminApi: {
    me: vi.fn(),
    listOrgs: vi.fn(),
    getOrg: vi.fn(),
    suspendOrg: vi.fn(),
    reactivateOrg: vi.fn(),
  },
}));

import { adminApi } from "@/lib/api/client";
import type { AdminMe, AdminOrgDetail, AdminOrgListItem } from "@/lib/api/types";
import { setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";

import { AdminTenantsPage } from "./AdminTenantsPage";

function staff(permissions: string[]): AdminMe {
  return { user_id: "s1", email: "ops@x.dev", staff_role: "superadmin", permissions };
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
});
