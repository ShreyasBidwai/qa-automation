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
import { clearToken, getToken } from "@/lib/auth/session";

import { SignInPage } from "./SignInPage";

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

describe("SignInPage", () => {
  beforeEach(() => {
    clearToken();
    vi.mocked(authApi.signIn).mockReset();
  });

  it("signs in and persists the token", async () => {
    vi.mocked(authApi.signIn).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        access_token: "tok-123",
        token_type: "bearer",
        user: { id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01" },
      },
    });

    renderWithAuth(<SignInPage />);
    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "a@b.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "hunter2!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(authApi.signIn).toHaveBeenCalledWith({
        email: "a@b.com",
        password: "hunter2!",
      }),
    );
    await waitFor(() => expect(getToken()).toBe("tok-123"));
  });

  it("shows an honest error on bad credentials", async () => {
    vi.mocked(authApi.signIn).mockResolvedValue({
      ok: false,
      status: 401,
      data: null,
      error: "invalid email or password",
    });

    renderWithAuth(<SignInPage />);
    fireEvent.change(screen.getByLabelText("Work email"), {
      target: { value: "a@b.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "nope" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid email or password",
    );
    expect(getToken()).toBeNull();
  });

  it("validates before calling the API", () => {
    renderWithAuth(<SignInPage />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter your email and password.",
    );
    expect(authApi.signIn).not.toHaveBeenCalled();
  });
});
