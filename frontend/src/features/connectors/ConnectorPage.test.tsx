import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConnectorPage } from "./ConnectorPage";

describe("ConnectorPage", () => {
  it("describes the Gitea connector and marks it coming soon", () => {
    render(<ConnectorPage kind="gitea" />);

    expect(screen.getByRole("heading", { name: "Gitea" })).toBeInTheDocument();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
    expect(screen.getByText(/ingest repos and open PRs/i)).toBeInTheDocument();
    // No credential input is rendered — nothing is collected until it ships.
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("describes the PM-tool connector", () => {
    render(<ConnectorPage kind="pm" />);

    expect(screen.getByRole("heading", { name: "PM tool" })).toBeInTheDocument();
    expect(
      screen.getByText(/push findings into your project tracker/i),
    ).toBeInTheDocument();
  });
});
