import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  authApi: {
    me: vi.fn(),
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    updateProfile: vi.fn(),
  },
}));

import { authApi } from "@/lib/api/client";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken } from "@/lib/auth/session";

import { SignUpPage } from "./SignUpPage";

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

const TOKEN = {
  ok: true as const,
  status: 201,
  data: {
    access_token: "tok-1",
    token_type: "bearer",
    user: { id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01" },
  },
};

describe("SignUpPage", () => {
  beforeEach(() => {
    clearToken();
    vi.mocked(authApi.signUp).mockReset();
    vi.mocked(authApi.updateProfile).mockReset();
  });

  it("creates the account and sets the display name via the profile", async () => {
    vi.mocked(authApi.signUp).mockResolvedValue(TOKEN);
    vi.mocked(authApi.updateProfile).mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "u1", email: "a@b.com", name: "Ada", created_at: "2026-01-01" },
    });

    renderWithAuth(<SignUpPage />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "a@b.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "longenough" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(authApi.signUp).toHaveBeenCalledWith({
        email: "a@b.com",
        password: "longenough",
      }),
    );
    await waitFor(() =>
      expect(authApi.updateProfile).toHaveBeenCalledWith({ name: "Ada" }),
    );
  });

  it("rejects a too-short password before calling the API", () => {
    renderWithAuth(<SignUpPage />);
    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "a@b.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "short" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(screen.getByRole("alert")).toHaveTextContent("at least 8 characters");
    expect(authApi.signUp).not.toHaveBeenCalled();
  });

  it("surfaces a duplicate-email error", async () => {
    vi.mocked(authApi.signUp).mockResolvedValue({
      ok: false,
      status: 409,
      data: null,
      error: "email already registered",
    });

    renderWithAuth(<SignUpPage />);
    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "taken@b.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "longenough" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "email already registered",
    );
  });
});
