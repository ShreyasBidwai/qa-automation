import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  projectApi: { create: vi.fn() },
  documentApi: { list: vi.fn(), upload: vi.fn(), remove: vi.fn() },
  credentialApi: { get: vi.fn(), put: vi.fn(), remove: vi.fn() },
  authConfigApi: { get: vi.fn(), put: vi.fn(), remove: vi.fn() },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import {
  authConfigApi,
  credentialApi,
  documentApi,
  projectApi,
} from "@/lib/api/client";

import { CreateProjectForm } from "./CreateProjectForm";

describe("CreateProjectForm", () => {
  beforeEach(() => {
    vi.mocked(projectApi.create).mockReset();
    // The post-registration setup step mounts the credential + document cards.
    vi.mocked(documentApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [], total: 0 },
    });
    vi.mocked(credentialApi.get).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        mode: "polaris_creates",
        identifier: null,
        has_credentials: false,
        has_totp: false,
      },
    });
    vi.mocked(authConfigApi.get).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        configured: false,
        login_url: null,
        username_selector: null,
        password_selector: null,
        submit_selector: null,
        otp_selector: null,
        otp_submit_selector: null,
        success_selector: null,
      },
    });
  });

  it("validates required fields and does not submit when empty", () => {
    render(<CreateProjectForm />);
    fireEvent.click(screen.getByRole("button", { name: "Register project" }));

    expect(screen.getByText("Enter a project name.")).toBeInTheDocument();
    expect(screen.getByText("Enter the repository URL.")).toBeInTheDocument();
    expect(projectApi.create).not.toHaveBeenCalled();
  });

  it("submits the typed project body", async () => {
    vi.mocked(projectApi.create).mockResolvedValue({
      ok: true,
      status: 201,
      data: {
        id: "p1",
        name: "Demo",
        slug: "demo-1",
        repo_url: "https://git/x.git",
        app_url: null,
        auth_config_ref: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    });

    render(<CreateProjectForm />);
    fireEvent.change(screen.getByLabelText("Project name"), {
      target: { value: "Demo" },
    });
    fireEvent.change(screen.getByLabelText("Repository URL"), {
      target: { value: "https://git/x.git" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register project" }));

    await waitFor(() =>
      expect(projectApi.create).toHaveBeenCalledWith({
        name: "Demo",
        repo_url: "https://git/x.git",
        app_url: null,
        stack: null,
        auth_config_ref: null,
      }),
    );
  });

  it("offers sign-in setup (login page + target account) on the success screen", async () => {
    vi.mocked(projectApi.create).mockResolvedValue({
      ok: true,
      status: 201,
      data: {
        id: "p1",
        name: "Demo",
        slug: "demo-1",
        repo_url: "https://git/x.git",
        app_url: null,
        auth_config_ref: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    });

    render(<CreateProjectForm />);
    fireEvent.change(screen.getByLabelText("Project name"), {
      target: { value: "Demo" },
    });
    fireEvent.change(screen.getByLabelText("Repository URL"), {
      target: { value: "https://git/x.git" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register project" }));

    // Both sign-in sections mount at registration — WHERE (login page) + WHO (target
    // account) — so Polaris can sign in during a run, not only later in settings.
    expect(
      await screen.findByRole("heading", { name: "Login page" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Target account" })).toBeInTheDocument();
    expect(authConfigApi.get).toHaveBeenCalledWith("p1");
    expect(credentialApi.get).toHaveBeenCalledWith("p1");
  });
});
