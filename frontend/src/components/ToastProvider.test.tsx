import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "./ToastProvider";
import { useToast } from "./useToast";

function NotifyButton({
  label,
  ...toast
}: {
  label: string;
  title: string;
  description?: string;
  tone?: "info" | "success" | "error";
  durationMs?: number;
  action?: { label: string; onClick: () => void };
}) {
  const { notify } = useToast();
  return (
    <button type="button" onClick={() => notify(toast)}>
      {label}
    </button>
  );
}

describe("ToastProvider / useToast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a toast with the given title, description, and role=status/aria-live=polite", () => {
    render(
      <ToastProvider>
        <NotifyButton label="fire" title="Run completed" description="42 tests" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));

    const toast = screen.getByRole("status");
    expect(toast).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Run completed")).toBeInTheDocument();
    expect(screen.getByText("42 tests")).toBeInTheDocument();
  });

  it("auto-dismisses after the default duration", async () => {
    render(
      <ToastProvider>
        <NotifyButton label="fire" title="Info toast" tone="info" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));
    expect(screen.getByRole("status")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("gives error toasts a longer default duration than info/success", async () => {
    render(
      <ToastProvider>
        <NotifyButton label="fire" title="Run failed" tone="error" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByRole("status")).toBeInTheDocument(); // still up past the info default

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("dismisses immediately on the close button, before the timer fires", () => {
    render(
      <ToastProvider>
        <NotifyButton label="fire" title="Dismiss me" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("runs the action's onClick and dismisses the toast when its action is clicked", () => {
    const onClick = vi.fn();
    render(
      <ToastProvider>
        <NotifyButton
          label="fire"
          title="Run completed"
          action={{ label: "View", onClick }}
        />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire"));
    fireEvent.click(screen.getByRole("button", { name: "View" }));

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("stacks multiple toasts, each dismissible independently", () => {
    render(
      <ToastProvider>
        <NotifyButton label="fire-a" title="First" />
        <NotifyButton label="fire-b" title="Second" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByText("fire-a"));
    fireEvent.click(screen.getByText("fire-b"));

    expect(screen.getAllByRole("status")).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "Dismiss" })[0]);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByText("Second")).toBeInTheDocument();
  });
});
