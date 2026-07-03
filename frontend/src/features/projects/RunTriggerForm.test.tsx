import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  runApi: { create: vi.fn() },
  projectApi: { importTests: vi.fn() },
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

  it("sends a mode_c prompt body (describe-it is the default)", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.change(screen.getByLabelText("What to test"), {
      target: { value: "Check the cart" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_c",
        prompt: "Check the cart",
      }),
    );
  });

  it("fills the prompt from an example chip", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(
      screen.getByRole("button", { name: "orders require authentication" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_c",
        prompt: "orders require authentication",
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
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });

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
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });

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
    fireEvent.change(screen.getByLabelText("CSV file"), { target: { files: [file] } });

    expect(await screen.findByRole("alert")).toHaveTextContent("CSV too large");
  });
});
