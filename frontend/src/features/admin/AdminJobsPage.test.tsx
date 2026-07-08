import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  adminApi: { me: vi.fn(), cancelJob: vi.fn(), requeueJob: vi.fn() },
  opsApi: { queue: vi.fn(), jobs: vi.fn() },
}));

import { adminApi, opsApi } from "@/lib/api/client";
import type { AdminMe, JobSummary, QueueStats } from "@/lib/api/types";
import { setToken } from "@/lib/auth/session";
import { resetStaffCache } from "@/lib/auth/useStaff";

import { AdminJobsPage } from "./AdminJobsPage";

function staff(permissions: string[]): AdminMe {
  return { user_id: "s1", email: "ops@x.dev", staff_role: "superadmin", permissions };
}

function queue(over: Partial<QueueStats> = {}): QueueStats {
  return {
    queued: 1,
    running: 0,
    succeeded: 5,
    failed: 2,
    cancelled: 0,
    stuck: 0,
    total: 8,
    runner_healthy: true,
    ...over,
  };
}

function job(over: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "job-1234abcd",
    kind: "ingest",
    status: "failed",
    project_id: "p1",
    mode: null,
    attempts: 1,
    max_attempts: 3,
    detail: null,
    created_at: "2026-02-01T00:00:00Z",
    locked_at: null,
    finished_at: "2026-02-01T00:05:00Z",
    ...over,
  };
}

function ok<T>(data: T) {
  return { ok: true, status: 200, data };
}

describe("AdminJobsPage", () => {
  beforeEach(() => {
    resetStaffCache();
    setToken("staff-token");
    vi.mocked(adminApi.me).mockReset();
    vi.mocked(adminApi.requeueJob).mockReset();
    vi.mocked(opsApi.queue).mockReset();
    vi.mocked(opsApi.jobs).mockReset();
    vi.mocked(adminApi.me).mockResolvedValue(ok(staff(["view_ops", "manage_jobs"])));
    vi.mocked(opsApi.queue).mockResolvedValue(ok(queue()));
  });

  it("renders the queue stats header and the jobs table", async () => {
    vi.mocked(opsApi.jobs).mockResolvedValue(ok({ items: [job()], total: 1 }));

    render(<AdminJobsPage />);

    expect(await screen.findByText("ingest")).toBeInTheDocument();
    // The queue snapshot strip renders the runner-health signal.
    expect(screen.getByText("Runner healthy")).toBeInTheDocument();
    await waitFor(() =>
      expect(opsApi.jobs).toHaveBeenCalledWith({ status: undefined, limit: 100 }),
    );
  });

  it("requeues a failed job (manage_jobs)", async () => {
    vi.mocked(opsApi.jobs).mockResolvedValue(ok({ items: [job()], total: 1 }));
    vi.mocked(adminApi.requeueJob).mockResolvedValue(
      ok(job({ id: "job-new", status: "queued" })),
    );

    render(<AdminJobsPage />);

    const requeue = await screen.findByRole("button", { name: "Requeue" });
    fireEvent.click(requeue);

    await waitFor(() =>
      expect(adminApi.requeueJob).toHaveBeenCalledWith("job-1234abcd"),
    );
  });

  it("hides job actions without manage_jobs", async () => {
    vi.mocked(adminApi.me).mockResolvedValue(ok(staff(["view_ops"]))); // read-only
    vi.mocked(opsApi.jobs).mockResolvedValue(ok({ items: [job()], total: 1 }));

    render(<AdminJobsPage />);

    expect(await screen.findByText("ingest")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Requeue" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });
});
