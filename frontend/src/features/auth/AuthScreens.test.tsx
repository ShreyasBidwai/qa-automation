import { fireEvent, render, screen } from "@testing-library/react";
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

import { AuthProvider } from "@/lib/auth/AuthContext";
import { clearToken } from "@/lib/auth/session";

import { ForgotPasswordPage } from "./ForgotPasswordPage";
import { SignInPage } from "./SignInPage";
import { SignUpPage } from "./SignUpPage";

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

describe("auth screens", () => {
  beforeEach(() => clearToken());

  it("sign in renders its fields and a create-account link", () => {
    renderWithAuth(<SignInPage />);

    expect(
      screen.getByRole("heading", { name: "Sign in to Polaris" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create account" })).toBeInTheDocument();
  });

  it("sign up renders its fields and a sign-in link", () => {
    renderWithAuth(<SignUpPage />);

    expect(
      screen.getByRole("heading", { name: "Create your account" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("forgot renders the reset request and is honest that it isn't wired yet", () => {
    renderWithAuth(<ForgotPasswordPage />);

    expect(
      screen.getByRole("heading", { name: "Reset your password" }),
    ).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Send reset link" });
    expect(submit).toBeInTheDocument();

    fireEvent.click(submit);
    expect(screen.getByText(/available yet/i)).toBeInTheDocument();
  });
});
