import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ runApi: { create: vi.fn() } }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { runApi } from "@/lib/api/client";

import { RunTriggerForm } from "./RunTriggerForm";

describe("RunTriggerForm", () => {
  beforeEach(() => {
    vi.mocked(runApi.create).mockReset();
    vi.mocked(runApi.create).mockResolvedValue({
      ok: true,
      status: 202,
      data: { run_id: "r1", status: "pending" },
    });
  });

  it("starts a mode_b full-sweep run with the right body", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.click(screen.getByRole("button", { name: "Run tests" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "full_sweep",
      }),
    );
  });

  it("sends a change_impact changeset as an array of paths", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.change(screen.getByLabelText("Selection"), {
      target: { value: "change_impact" },
    });
    fireEvent.change(screen.getByLabelText("Changed files"), {
      target: { value: "app/A.php\napp/B.php\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tests" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_b",
        strategy: "change_impact",
        changeset: ["app/A.php", "app/B.php"],
      }),
    );
  });

  it("sends a mode_c prompt body", async () => {
    render(<RunTriggerForm projectId="p1" />);
    fireEvent.change(screen.getByLabelText("Mode"), {
      target: { value: "mode_c" },
    });
    fireEvent.change(screen.getByLabelText("What to test"), {
      target: { value: "Check the cart" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run tests" }));

    await waitFor(() =>
      expect(runApi.create).toHaveBeenCalledWith("p1", {
        mode: "mode_c",
        prompt: "Check the cart",
      }),
    );
  });
});
