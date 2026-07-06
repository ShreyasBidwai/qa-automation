import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  runApi: { create: vi.fn() },
  projectApi: { importTests: vi.fn(), modules: vi.fn() },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));
vi.mock("@/components/Link", () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => (
    <a href={to}>{children}</a>
  ),
}));

import type React from "react";

import { projectApi, runApi } from "@/lib/api/client";
import { navigate } from "@/lib/router";

import { RunTriggerForm } from "./RunTriggerForm";

describe("RunTriggerForm", () => {
  beforeEach(() => {
    vi.mocked(navigate).mockReset();
    vi.mocked(projectApi.importTests).mockReset();
    vi.mocked(projectApi.modules)
      .mockReset()
      .mockResolvedValue({
        ok: true,
        status: 200,
        data: {
          modules: [
            {
              key: "orders",
              label: "Orders",
              endpoint_count: 3,
              page_count: 1,
              total: 4,
            },
            {
              key: "users",
              label: "Users",
              endpoint_count: 2,
              page_count: 0,
              total: 2,
            },
          ],
        },
      });
    vi.mocked(runApi.create).mockReset();
    vi.mocked(runApi.create).mockResolvedValue({
      ok: true,
      status: 202,
      data: { run_id: "r1", status: "queued" },
    });
  });

  it("starts a mode_b full-sweep run, then lands on the live view to watch it", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "full_sweep",
      }),
    );
    // Straight to the watchable live run, not the coarse status page.
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/runs/r1/live"));
  });

  it("sends a change_impact changeset as an array of paths", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Test only what changed/ }));
    fireEvent.change(screen.getByLabelText("Changed files"), {
      target: { value: "app/A.php\napp/B.php\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "change_impact",
        changeset: ["app/A.php", "app/B.php"],
      }),
    );
  });

  it("sends a mode_c prompt body defaulting to the UI authoring layer", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.change(screen.getByLabelText("What to test"), {
      target: { value: "Check the cart" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_c",
        prompt: "Check the cart",
        layer: "ui",
      }),
    );
    // Authoring lands on the Tests viewer (it polls the job), not a live-run page.
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/projects/p1/tests?authoring=r1"),
    );
  });

  it("authors at the API layer when API is chosen", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /^API contract/ }));
    fireEvent.change(screen.getByLabelText("What to test"), {
      target: { value: "orders reject an unauthenticated POST" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_c",
        prompt: "orders reject an unauthenticated POST",
        layer: "api",
      }),
    );
  });

  it("fills the prompt from an example chip", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(
      screen.getByRole("button", { name: "login rejects a wrong password" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_c",
        prompt: "login rejects a wrong password",
        layer: "ui",
      }),
    );
  });

  it("sends only the selected layers when some are turned off", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    // Default is all on (= omit the field); turning DB off sends the explicit subset.
    fireEvent.click(screen.getByRole("checkbox", { name: /DB/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "full_sweep",
        layers: ["ui", "api"],
      }),
    );
  });

  it("blocks the run with a clear message when every layer is turned off", () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /UI/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /API/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /DB/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    expect(screen.getByText("Select at least one layer to test")).toBeInTheDocument();
    expect(runApi.create).not.toHaveBeenCalled();
  });

  it("scopes an autonomous run to the picked modules (layers auto-set to fit)", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Test specific modules/ }));

    // Orders has API + UI targets, so picking it auto-sets the layers to ui+api
    // (DB isn't a per-module target, so it drops off).
    fireEvent.click(await screen.findByRole("checkbox", { name: /Orders/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "full_sweep",
        modules: ["orders"],
        layers: ["ui", "api"],
      }),
    );
  });

  it("auto-sets the layers to what an API-only module supports", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Test specific modules/ }));

    // Users has endpoints but no pages → picking it leaves API on, UI off.
    fireEvent.click(await screen.findByRole("checkbox", { name: /Users/ }));
    expect(screen.getByRole("checkbox", { name: /^UI/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^API/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "full_sweep",
        modules: ["users"],
        layers: ["api"],
      }),
    );
  });

  it("filters the module list by the search box", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Test specific modules/ }));

    expect(await screen.findByRole("checkbox", { name: /Orders/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Users/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search modules"), {
      target: { value: "ord" },
    });
    expect(screen.getByRole("checkbox", { name: /Orders/ })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Users/ })).toBeNull();
  });

  it("blocks a module-scoped run with no module selected", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("radio", { name: /Autonomous/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Test specific modules/ }));
    await screen.findByRole("checkbox", { name: /Orders/ });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    expect(screen.getByText("Select at least one module to test.")).toBeInTheDocument();
    expect(runApi.create).not.toHaveBeenCalled();
  });

  it("imports a CSV and shows the summary + a link to the tests", async () => {
    vi.mocked(projectApi.importTests).mockResolvedValue({
      ok: true,
      status: 200,
      data: { total: 2, created: 2, updated: 0, errors: [] },
    });
    render(<RunTriggerForm projectId="p1" />);

    const file = new File(["method,path,expected_status\nGET,api/x,200\n"], "t.csv", {
      type: "text/csv",
    });
    fireEvent.change(screen.getByLabelText("CSV file"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(projectApi.importTests).toHaveBeenCalledWith("p1", file),
    );
    expect(await screen.findByText(/Imported 2 tests \(2 new\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View tests/ })).toHaveAttribute(
      "href",
      "/projects/p1/tests",
    );
  });

  it("surfaces skipped rows from a partial import", async () => {
    vi.mocked(projectApi.importTests).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        total: 1,
        created: 1,
        updated: 0,
        errors: [{ row: 2, message: "method 'NOPE' must be one of [...]" }],
      },
    });
    render(<RunTriggerForm projectId="p1" />);

    const file = new File(["x"], "t.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("CSV file"), {
      target: { files: [file] },
    });

    expect(await screen.findByText(/1 row skipped/)).toBeInTheDocument();
    expect(screen.getByText(/method 'NOPE'/)).toBeInTheDocument();
  });

  it("shows an error when the import request fails", async () => {
    vi.mocked(projectApi.importTests).mockResolvedValue({
      ok: false,
      status: 413,
      data: null,
      error: "CSV too large",
    });
    render(<RunTriggerForm projectId="p1" />);

    const file = new File(["x"], "t.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("CSV file"), {
      target: { files: [file] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("CSV too large");
  });
});
