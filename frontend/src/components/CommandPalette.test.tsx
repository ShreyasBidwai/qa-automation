import { fireEvent, render, screen, within } from "@testing-library/react";
import { act, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ searchApi: { search: vi.fn() } }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import type { ApiResult } from "@/lib/api/client";
import { searchApi } from "@/lib/api/client";
import type { SearchResponse } from "@/lib/api/types";
import { navigate } from "@/lib/router";

import { CommandPalette } from "./CommandPalette";

const DEBOUNCE_MS = 200;

function ok(data: SearchResponse) {
  return { ok: true, status: 200, data };
}

const RESULTS: SearchResponse = {
  query: "checkout",
  items: [
    {
      type: "project",
      id: "p1",
      label: "Checkout Service",
      subtitle: "checkout-service",
      url: "/projects/p1",
    },
    {
      type: "finding",
      id: "f1",
      label: "Checkout 500",
      subtitle: "Checkout Service",
      url: "/findings/f1",
    },
  ],
};

describe("CommandPalette", () => {
  beforeEach(() => {
    vi.mocked(searchApi.search).mockReset();
    vi.mocked(navigate).mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when closed", () => {
    render(<CommandPalette open={false} onClose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens with an empty, focused input and a hint (no request fired)", () => {
    render(<CommandPalette open onClose={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveFocus();
    expect(screen.getByText(/Type to jump to/)).toBeInTheDocument();
    expect(searchApi.search).not.toHaveBeenCalled();
  });

  it("debounces the search call while typing", async () => {
    vi.mocked(searchApi.search).mockResolvedValue(ok(RESULTS));
    render(<CommandPalette open onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "checkout" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 50);
    });
    expect(searchApi.search).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(searchApi.search).toHaveBeenCalledTimes(1);
    expect(searchApi.search).toHaveBeenCalledWith("checkout");
    const options = screen.getAllByRole("option");
    expect(within(options[0]).getByText("Checkout Service")).toBeInTheDocument();
    expect(within(options[1]).getByText("Checkout 500")).toBeInTheDocument();
  });

  it("discards a stale response that resolves after a newer keystroke's", async () => {
    let resolveFirst!: (value: ApiResult<SearchResponse>) => void;
    vi.mocked(searchApi.search).mockImplementationOnce(
      () =>
        new Promise<ApiResult<SearchResponse>>((resolve) => (resolveFirst = resolve)),
    );
    render(<CommandPalette open onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "che" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });

    vi.mocked(searchApi.search).mockResolvedValueOnce(
      ok({
        query: "check",
        items: [
          {
            type: "project",
            id: "p2",
            label: "Second Query Result",
            subtitle: null,
            url: "/projects/p2",
          },
        ],
      }),
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "check" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });
    expect(screen.getByText("Second Query Result")).toBeInTheDocument();

    // The first ("che") request finally resolves — it must NOT clobber the newer result.
    await act(async () => {
      resolveFirst(ok(RESULTS));
      await Promise.resolve();
    });
    expect(screen.getByText("Second Query Result")).toBeInTheDocument();
    expect(screen.queryByText("Checkout Service")).toBeNull();
  });

  it("shows a loading state while a search is in flight", async () => {
    vi.mocked(searchApi.search).mockImplementation(() => new Promise(() => {}));
    render(<CommandPalette open onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "x" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });
    expect(screen.getByText("Searching…")).toBeInTheDocument();
  });

  it("shows an error message when the search fails", async () => {
    vi.mocked(searchApi.search).mockResolvedValue({
      ok: false,
      status: 500,
      data: null,
      error: "Server boom",
    });
    render(<CommandPalette open onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "x" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });
    expect(screen.getByText("Server boom")).toBeInTheDocument();
  });

  it("shows a no-results message for a query with no matches", async () => {
    vi.mocked(searchApi.search).mockResolvedValue(ok({ query: "zzz", items: [] }));
    render(<CommandPalette open onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzz" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });
    expect(screen.getByText(/No results for/)).toBeInTheDocument();
  });

  it("navigates + closes on Enter, defaulting to the first result", async () => {
    vi.mocked(searchApi.search).mockResolvedValue(ok(RESULTS));
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "checkout" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });
    expect(screen.getAllByRole("option")).toHaveLength(2);

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Enter" });
    expect(navigate).toHaveBeenCalledWith("/projects/p1");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("moves the active selection with ArrowDown/ArrowUp and navigates the active one", async () => {
    vi.mocked(searchApi.search).mockResolvedValue(ok(RESULTS));
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "checkout" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });
    expect(screen.getAllByRole("option")).toHaveLength(2);

    const dialog = screen.getByRole("dialog");
    fireEvent.keyDown(dialog, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(dialog, { key: "Enter" });
    expect(navigate).toHaveBeenCalledWith("/findings/f1");
  });

  it("navigates + closes when a result is clicked", async () => {
    vi.mocked(searchApi.search).mockResolvedValue(ok(RESULTS));
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "checkout" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    });

    fireEvent.click(screen.getByText("Checkout 500"));
    expect(navigate).toHaveBeenCalledWith("/findings/f1");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape and restores focus to the trigger", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <CommandPalette open={open} onClose={() => setOpen(false)} />
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open" });
    trigger.focus();
    fireEvent.click(trigger);

    expect(screen.getByRole("combobox")).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("closes when the backdrop is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(<CommandPalette open onClose={onClose} />);
    const backdrop = container.querySelector('[aria-hidden="true"]')!;
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
