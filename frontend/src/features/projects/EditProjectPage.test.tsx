import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  projectApi: { get: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { projectApi } from "@/lib/api/client";
import { navigate } from "@/lib/router";
import type { Project } from "@/lib/api/types";

import { EditProjectPage } from "./EditProjectPage";

const PROJECT: Project = {
  id: "p1",
  name: "Acme Billing API",
  slug: "acme-billing",
  repo_url: "https://github.com/acme/billing.git",
  app_url: "https://staging.acme.com",
  auth_config_ref: null,
  stack: "Laravel",
  created_at: "2026-06-01T00:00:00Z",
};

describe("EditProjectPage", () => {
  beforeEach(() => {
    vi.mocked(projectApi.get).mockReset();
    vi.mocked(projectApi.update).mockReset();
    vi.mocked(projectApi.remove).mockReset();
    vi.mocked(navigate).mockReset();
    vi.mocked(projectApi.get).mockResolvedValue({
      ok: true,
      status: 200,
      data: PROJECT,
    });
  });

  it("pre-fills the form and saves the edited values", async () => {
    vi.mocked(projectApi.update).mockResolvedValue({
      ok: true,
      status: 200,
      data: { ...PROJECT, name: "Acme Billing v2" },
    });

    render(<EditProjectPage projectId="p1" />);

    const nameInput = (await screen.findByLabelText(
      "Project name",
    )) as HTMLInputElement;
    expect(nameInput.value).toBe("Acme Billing API");

    fireEvent.change(nameInput, { target: { value: "Acme Billing v2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(projectApi.update).toHaveBeenCalledWith("p1", {
        name: "Acme Billing v2",
        repo_url: "https://github.com/acme/billing.git",
        app_url: "https://staging.acme.com",
        stack: "Laravel",
      }),
    );
    expect(await screen.findByText("Changes saved.")).toBeInTheDocument();
  });

  it("deletes the project after confirmation and returns to the list", async () => {
    vi.mocked(projectApi.remove).mockResolvedValue({
      ok: true,
      status: 204,
      data: null,
    });

    render(<EditProjectPage projectId="p1" />);
    await screen.findByLabelText("Project name");

    fireEvent.click(screen.getByRole("button", { name: "Delete project" }));
    // A confirmation gate appears before anything is destroyed.
    expect(screen.getByText("Delete this project?")).toBeInTheDocument();
    expect(projectApi.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    await waitFor(() => expect(projectApi.remove).toHaveBeenCalledWith("p1"));
    expect(navigate).toHaveBeenCalledWith("/projects");
  });
});
