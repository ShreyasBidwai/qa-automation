import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  authApi: { updateProfile: vi.fn(), changePassword: vi.fn() },
  orgApi: {
    listOrgs: vi.fn(),
    listMembers: vi.fn(),
    listInvites: vi.fn(),
    invite: vi.fn(),
    changeRole: vi.fn(),
    removeMember: vi.fn(),
  },
}));

const setUser = vi.fn();
vi.mock("@/lib/auth/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      name: "Jordan Lee",
      email: "jordan@acme.test",
      created_at: "2026-01-01",
    },
    setUser,
  }),
}));

import { authApi, orgApi } from "@/lib/api/client";
import type { InviteResponse, MemberResponse, OrgRoleName } from "@/lib/api/types";

import { AccountPage } from "./AccountPage";

function ok<T>(data: T) {
  return { ok: true as const, status: 200, data };
}

function member(over: Partial<MemberResponse>): MemberResponse {
  return {
    user_id: "u2",
    email: "sam@acme.test",
    name: "Sam Rivera",
    role: "admin",
    created_at: "2026-01-02",
    ...over,
  };
}

const PENDING: InviteResponse = {
  id: "i1",
  email: "priya@acme.test",
  role: "member",
  expires_at: "2026-12-01",
  accepted_at: null,
  created_at: "2026-01-03",
};

function orgsPage(role: OrgRoleName) {
  return ok({
    items: [
      {
        id: "o1",
        name: "Acme",
        is_personal: false,
        role,
        created_at: "2026-01-01",
      },
    ],
    total: 1,
  });
}

const MEMBERS = ok({
  items: [
    member({
      user_id: "u1",
      name: "Jordan Lee",
      email: "jordan@acme.test",
      role: "owner",
    }),
    member({
      user_id: "u2",
      name: "Sam Rivera",
      email: "sam@acme.test",
      role: "admin",
    }),
    member({
      user_id: "u3",
      name: "Alex Chen",
      email: "alex@acme.test",
      role: "member",
    }),
  ],
  total: 3,
});

describe("AccountPage — Profile", () => {
  beforeEach(() => {
    vi.mocked(authApi.updateProfile).mockReset();
    vi.mocked(authApi.changePassword).mockReset();
    setUser.mockReset();
  });

  it("shows the current user and saves the profile (PATCH /auth/me)", async () => {
    vi.mocked(authApi.updateProfile).mockResolvedValue(
      ok({ id: "u1", name: "Jordan L.", email: "jordan@acme.test", created_at: "x" }),
    );

    render(<AccountPage />);
    const nameInput = screen.getByLabelText("Name") as HTMLInputElement;
    expect(nameInput.value).toBe("Jordan Lee");

    fireEvent.change(nameInput, { target: { value: "Jordan L." } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(authApi.updateProfile).toHaveBeenCalledWith({
        name: "Jordan L.",
        email: "jordan@acme.test",
      }),
    );
    expect(await screen.findByText("Changes saved.")).toBeInTheDocument();
    expect(setUser).toHaveBeenCalled();
  });

  it("validates the confirm field locally before calling the API", () => {
    render(<AccountPage />);
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "longenough" },
    });
    fireEvent.change(screen.getByLabelText("Confirm"), {
      target: { value: "different" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    expect(screen.getByText("Passwords don't match.")).toBeInTheDocument();
    expect(authApi.changePassword).not.toHaveBeenCalled();
  });

  it("surfaces the B11 field-level password-policy message (422 errors[])", async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue({
      ok: false,
      status: 422,
      data: null,
      error: "Password must be at least 8 characters.",
      fieldErrors: [
        { field: "new_password", message: "Password must be at least 8 characters." },
      ],
    });

    render(<AccountPage />);
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "old-one" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "short" },
    });
    fireEvent.change(screen.getByLabelText("Confirm"), {
      target: { value: "short" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    await waitFor(() =>
      expect(authApi.changePassword).toHaveBeenCalledWith({
        current_password: "old-one",
        new_password: "short",
      }),
    );
    expect(
      await screen.findByText("Password must be at least 8 characters."),
    ).toBeInTheDocument();
  });
});

describe("AccountPage — Team (RBAC gated by the API role)", () => {
  beforeEach(() => {
    vi.mocked(orgApi.listOrgs).mockReset();
    vi.mocked(orgApi.listMembers).mockReset();
    vi.mocked(orgApi.listInvites).mockReset();
    vi.mocked(orgApi.invite).mockReset();
    vi.mocked(orgApi.removeMember).mockReset();
  });

  it("as owner: lists members, pending invites, the invite form, and member actions", async () => {
    vi.mocked(orgApi.listOrgs).mockResolvedValue(orgsPage("owner"));
    vi.mocked(orgApi.listMembers).mockResolvedValue(MEMBERS);
    vi.mocked(orgApi.listInvites).mockResolvedValue(ok({ items: [PENDING], total: 1 }));
    vi.mocked(orgApi.removeMember).mockResolvedValue({
      ok: true,
      status: 204,
      data: null,
    });

    render(<AccountPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Team" }));

    expect(await screen.findByText("Sam Rivera")).toBeInTheDocument();
    expect(screen.getByText("Alex Chen")).toBeInTheDocument();
    // A pending invite shows honestly (email + badge), since the API has only the email.
    expect(screen.getByText("priya@acme.test")).toBeInTheDocument();
    expect(screen.getByText("Invite pending")).toBeInTheDocument();
    // Manager-only invite form.
    expect(screen.getByText("Invite a member")).toBeInTheDocument();

    // The self row is not self-manageable; another member is.
    expect(screen.queryByLabelText("Manage Jordan Lee")).toBeNull();
    fireEvent.click(screen.getByLabelText("Manage Sam Rivera"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove from team" }));

    await waitFor(() => expect(orgApi.removeMember).toHaveBeenCalledWith("o1", "u2"));
  });

  it("as a non-manager member: read-only — no invite form, no member actions", async () => {
    vi.mocked(orgApi.listOrgs).mockResolvedValue(orgsPage("member"));
    vi.mocked(orgApi.listMembers).mockResolvedValue(MEMBERS);

    render(<AccountPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Team" }));

    expect(await screen.findByText("Sam Rivera")).toBeInTheDocument();
    // Not authoritative — the API enforces — but the client hides what it would refuse.
    expect(screen.queryByText("Invite a member")).toBeNull();
    expect(screen.queryByLabelText("Manage Sam Rivera")).toBeNull();
    // A non-manager never even fetches invites.
    expect(orgApi.listInvites).not.toHaveBeenCalled();
  });

  it("invite: surfaces a 429 rate-limit message honestly", async () => {
    vi.mocked(orgApi.listOrgs).mockResolvedValue(orgsPage("owner"));
    vi.mocked(orgApi.listMembers).mockResolvedValue(MEMBERS);
    vi.mocked(orgApi.listInvites).mockResolvedValue(ok({ items: [], total: 0 }));
    vi.mocked(orgApi.invite).mockResolvedValue({
      ok: false,
      status: 429,
      data: null,
      error: "Too many attempts. Please try again in 30 seconds.",
      retryAfter: 30,
    });

    render(<AccountPage />);
    fireEvent.click(screen.getByRole("tab", { name: "Team" }));
    await screen.findByText("Invite a member");

    fireEvent.change(screen.getByLabelText("Email to invite"), {
      target: { value: "new@acme.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));

    expect(
      await screen.findByText("Too many attempts. Please try again in 30 seconds."),
    ).toBeInTheDocument();
  });
});
