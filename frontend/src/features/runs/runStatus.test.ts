import { describe, expect, it } from "vitest";

import type { JobStatusValue } from "@/lib/api/types";

import { isTerminal, runRowStatusDescriptor, runStatusDescriptor } from "./runStatus";

describe("runRowStatusDescriptor", () => {
  it("gives ERRORED its own level, distinct from a real FAILED", () => {
    // A run that couldn't complete (infra) must not look like a run that found a bug
    // (architecture-review DO-FIRST #4).
    expect(runRowStatusDescriptor("errored").level).toBe("error");
    expect(runRowStatusDescriptor("failed").level).toBe("fail");
    expect(runRowStatusDescriptor("errored").level).not.toBe(
      runRowStatusDescriptor("failed").level,
    );
  });
});

describe("runStatusDescriptor", () => {
  // The backend JobStatus enum, verbatim (app/models/enums.py). Every one of these
  // reaches the UI over /jobs/{id} and /runs/{id} — the map MUST cover them all.
  const ALL: JobStatusValue[] = [
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
  ];

  it("maps every backend job status to a real badge (never undefined)", () => {
    for (const status of ALL) {
      const descriptor = runStatusDescriptor(status);
      // The regression this guards: a missing case returned undefined, and
      // StatusBadge then threw on `undefined.level` → the whole app fell into the
      // "Something went wrong on our end" error boundary the moment a build queued.
      expect(descriptor).toBeDefined();
      expect(descriptor.level).toBeTruthy();
      expect(descriptor.label).toBeTruthy();
    }
  });

  it("maps 'queued' — the real first status of a fresh build — to Queued", () => {
    expect(runStatusDescriptor("queued")).toEqual({ level: "info", label: "Queued" });
  });

  it("degrades an unknown/future status to a neutral badge instead of throwing", () => {
    // A status the backend adds before the UI models it must not crash the app.
    const descriptor = runStatusDescriptor("something_new" as JobStatusValue);
    expect(descriptor.level).toBe("neutral");
    expect(descriptor.label).toBe("something_new");
  });

  it("treats succeeded/failed/cancelled as terminal, queued/running as not", () => {
    expect(isTerminal("succeeded")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("cancelled")).toBe(true);
    expect(isTerminal("queued")).toBe(false);
    expect(isTerminal("running")).toBe(false);
  });
});
