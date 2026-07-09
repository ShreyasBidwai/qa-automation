import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  credentialApi: { get: vi.fn(), put: vi.fn(), remove: vi.fn() },
}));

import { credentialApi } from "@/lib/api/client";

import { ProjectCredentialsCard } from "./ProjectCredentialsCard";

function status(over: {
  mode?: string;
  identifier?: string | null;
  has_credentials?: boolean;
  has_totp?: boolean;
}) {
  return {
    ok: true,
    status: 200,
    data: {
      mode: over.mode ?? "polaris_creates",
      identifier: over.identifier ?? null,
      has_credentials: over.has_credentials ?? false,
      has_totp: over.has_totp ?? false,
    },
  };
}

describe("ProjectCredentialsCard", () => {
  beforeEach(() => {
    vi.mocked(credentialApi.get).mockReset();
    vi.mocked(credentialApi.put).mockReset();
    vi.mocked(credentialApi.remove).mockReset();
    vi.mocked(credentialApi.get).mockResolvedValue(status({}));
  });

  it("defaults to Polaris creating a test account", async () => {
    render(<ProjectCredentialsCard projectId="p1" />);
    const polaris = await screen.findByRole("radio", {
      name: /Let Polaris create a test account/,
    });
    expect(polaris).toBeChecked();
    expect(
      screen.getByRole("radio", { name: /Test a specific account/ }),
    ).not.toBeChecked();
  });

  it("saves a specific account and never displays the stored password", async () => {
    vi.mocked(credentialApi.get)
      .mockReset()
      .mockResolvedValueOnce(status({})) // mount: unconfigured
      .mockResolvedValue(
        status({
          mode: "specific_account",
          identifier: "qa@x.com",
          has_credentials: true,
        }),
      ); // after save: configured
    vi.mocked(credentialApi.put).mockResolvedValue(
      status({
        mode: "specific_account",
        identifier: "qa@x.com",
        has_credentials: true,
      }),
    );

    render(<ProjectCredentialsCard projectId="p1" />);
    await screen.findByRole("radio", { name: /Test a specific account/ });

    fireEvent.click(screen.getByRole("radio", { name: /Test a specific account/ }));
    fireEvent.change(screen.getByLabelText("Username, email, or mobile"), {
      target: { value: "qa@x.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "hunter2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(credentialApi.put).toHaveBeenCalledWith("p1", {
        mode: "specific_account",
        identifier: "qa@x.com",
        secret: "hunter2",
      }),
    );

    // After save: the saved state shows, the password field is gone, and the
    // plaintext is nowhere in the DOM (write-only).
    expect(await screen.findByText(/Credentials saved/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(screen.queryByDisplayValue("hunter2")).toBeNull();
  });

  it("shows the saved state for a configured account with no password field", async () => {
    vi.mocked(credentialApi.get)
      .mockReset()
      .mockResolvedValue(
        status({
          mode: "specific_account",
          identifier: "qa@x.com",
          has_credentials: true,
        }),
      );

    render(<ProjectCredentialsCard projectId="p1" />);

    expect(await screen.findByText(/Credentials saved/)).toBeInTheDocument();
    expect(screen.getByText("qa@x.com")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Replace credentials" }),
    ).toBeInTheDocument();
  });

  it("surfaces a 403 on save honestly", async () => {
    vi.mocked(credentialApi.put).mockResolvedValue({
      ok: false,
      status: 403,
      data: null,
      error: "forbidden",
    });

    render(<ProjectCredentialsCard projectId="p1" />);
    await screen.findByRole("radio", { name: /Test a specific account/ });

    fireEvent.click(screen.getByRole("radio", { name: /Test a specific account/ }));
    fireEvent.change(screen.getByLabelText("Username, email, or mobile"), {
      target: { value: "qa@x.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/manage-project role/)).toBeInTheDocument();
  });

  it("shows a permission message when reading credentials is forbidden", async () => {
    vi.mocked(credentialApi.get).mockReset().mockResolvedValue({
      ok: false,
      status: 403,
      data: null,
      error: "forbidden",
    });

    render(<ProjectCredentialsCard projectId="p1" />);
    expect(
      await screen.findByText(/requires the manage-project role/),
    ).toBeInTheDocument();
  });
});
