import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ adminApi: { me: vi.fn() } }));

import { adminApi } from "@/lib/api/client";
import type { AdminMe } from "@/lib/api/types";

import { clearToken, setToken } from "./session";
import { resetStaffCache, useStaff } from "./useStaff";

function me(permissions: string[]): AdminMe {
  return {
    user_id: "s1",
    email: "ops@polaris.dev",
    staff_role: "superadmin",
    permissions,
  };
}

describe("useStaff", () => {
  beforeEach(() => {
    resetStaffCache();
    clearToken();
    vi.mocked(adminApi.me).mockReset();
  });

  it("resolves a staff caller's identity + permissions", async () => {
    setToken("staff-token");
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: me(["view_ops", "view_tenants"]),
    });

    const { result } = renderHook(() => useStaff());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.staff?.email).toBe("ops@polaris.dev");
    // hasPerm reflects the granted permissions — and only those.
    expect(result.current.hasPerm("view_ops")).toBe(true);
    expect(result.current.hasPerm("view_tenants")).toBe(true);
    expect(result.current.hasPerm("manage_users")).toBe(false);
  });

  it("treats a 403 (not staff) as no access, never a crash", async () => {
    setToken("member-token");
    vi.mocked(adminApi.me).mockResolvedValue({
      ok: false,
      status: 403,
      data: null,
      error: "forbidden",
    });

    const { result } = renderHook(() => useStaff());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.staff).toBeNull();
    expect(result.current.hasPerm("view_ops")).toBe(false);
  });

  it("treats a signed-out caller as not staff without asking the API", async () => {
    // No token set in beforeEach → /admin/me is never called.
    const { result } = renderHook(() => useStaff());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.staff).toBeNull();
    expect(adminApi.me).not.toHaveBeenCalled();
  });
});
