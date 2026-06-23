import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HELP_SECTIONS } from "./helpContent";
import { HelpCenterPage } from "./HelpCenterPage";

// jsdom has no layout engine, so scrollIntoView is undefined — stub it so the
// jump path runs and we can assert it fired.
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

function sectionNav() {
  return within(screen.getByRole("navigation", { name: "Help sections" }));
}

describe("HelpCenterPage", () => {
  it("renders every section as a heading and a list entry", () => {
    render(<HelpCenterPage />);
    for (const section of HELP_SECTIONS) {
      expect(
        screen.getByRole("heading", { level: 2, name: section.title }),
      ).toBeInTheDocument();
    }
    expect(sectionNav().getAllByRole("button")).toHaveLength(HELP_SECTIONS.length);
  });

  it("exposes a keyboard-reachable search box with an accessible name", () => {
    render(<HelpCenterPage />);
    expect(screen.getByRole("searchbox", { name: "Search help" })).toBeInTheDocument();
  });

  it("filters the section list over titles and body text", () => {
    render(<HelpCenterPage />);
    const nav = sectionNav();
    // "amber" appears only in the trust-marks section's content.
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "amber" } });

    expect(nav.getByRole("button", { name: /Trust marks/ })).toBeInTheDocument();
    expect(nav.queryByRole("button", { name: /Findings/ })).not.toBeInTheDocument();
    expect(screen.getByText("1 of 15 sections")).toBeInTheDocument();
  });

  it("shows a helpful empty state when nothing matches", () => {
    render(<HelpCenterPage />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzzzz" } });
    expect(sectionNav().queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText(/No sections match/)).toBeInTheDocument();
  });

  it("jumps to a section and moves focus when a list entry is selected", () => {
    render(<HelpCenterPage />);
    fireEvent.click(sectionNav().getByRole("button", { name: /Run scope/ }));

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 2, name: "Run scope" })).toHaveFocus();
  });

  it("jumps to the first result when Enter is pressed in the search box", () => {
    render(<HelpCenterPage />);
    const search = screen.getByRole("searchbox");
    fireEvent.change(search, { target: { value: "amber" } });
    fireEvent.keyDown(search, { key: "Enter" });

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(
      screen.getByRole("heading", { level: 2, name: "Trust marks" }),
    ).toHaveFocus();
  });

  it("renders the trust-mark meanings so the symbols are explained in words", () => {
    render(<HelpCenterPage />);
    expect(screen.getByText(/follows from a real rule/)).toBeInTheDocument();
    expect(screen.getByText(/only pins down how the app behaves/)).toBeInTheDocument();
  });
});
