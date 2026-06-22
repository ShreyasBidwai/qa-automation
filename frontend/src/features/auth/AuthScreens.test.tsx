import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ForgotPasswordPage } from "./ForgotPasswordPage";
import { SignInPage } from "./SignInPage";
import { SignUpPage } from "./SignUpPage";

describe("auth screens (static placeholders)", () => {
  it("sign in renders its fields, a create-account link, and a not-wired notice", () => {
    render(<SignInPage />);

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create an account" })).toBeInTheDocument();
    // Honest about being a placeholder.
    expect(screen.getByText(/wired up yet/i)).toBeInTheDocument();
  });

  it("sign up renders its fields and a sign-in link", () => {
    render(<SignUpPage />);

    expect(
      screen.getByRole("heading", { name: "Create your account" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("forgot renders the reset request", () => {
    render(<ForgotPasswordPage />);

    expect(
      screen.getByRole("heading", { name: "Reset your password" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send reset link" })).toBeInTheDocument();
  });
});
