import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ projectApi: { create: vi.fn() } }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));
vi.mock("@/lib/registry", () => ({ rememberProject: vi.fn() }));

import { projectApi } from "@/lib/api/client";

import { CreateProjectForm } from "./CreateProjectForm";

describe("CreateProjectForm", () => {
  beforeEach(() => {
    vi.mocked(projectApi.create).mockReset();
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
        auth_config_ref: null,
      }),
    );
  });
});
