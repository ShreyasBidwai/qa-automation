import { afterEach, describe, expect, it, vi } from "vitest";

import { projectApi, runApi } from "./client";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

afterEach(() => {
  fetchMock.mockReset();
});

describe("api client", () => {
  it("POST /projects sends the typed body and parses the project", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          id: "p1",
          name: "Demo",
          slug: "demo-1",
          repo_url: "https://git/x.git",
          app_url: null,
          auth_config_ref: null,
          created_at: "2026-01-01T00:00:00Z",
        },
        201,
      ),
    );

    const result = await projectApi.create({
      name: "Demo",
      repo_url: "https://git/x.git",
      app_url: null,
      auth_config_ref: null,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      name: "Demo",
      repo_url: "https://git/x.git",
      app_url: null,
      auth_config_ref: null,
    });
    expect(result.ok).toBe(true);
    expect(result.data?.id).toBe("p1");
  });

  it("GET /runs/:id parses the run status", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ run_id: "r1", mode: "mode_b", status: "running", summary: null }),
    );

    const result = await runApi.get("r1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/runs/r1");
    expect(result.ok).toBe(true);
    expect(result.data?.status).toBe("running");
  });

  it("normalizes a problem+json error to ok:false with the detail", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          title: "Unprocessable Entity",
          detail: "Request validation failed.",
          code: "validation_error",
        },
        422,
      ),
    );

    const result = await runApi.create("p1", {
      mode: "mode_b",
      strategy: "change_impact",
    });

    expect(result.ok).toBe(false);
    expect(result.status).toBe(422);
    expect(result.error).toBe("Request validation failed.");
    expect(result.data).toBeNull();
  });

  it("returns a network error when fetch rejects", async () => {
    fetchMock.mockRejectedValue(new Error("boom"));

    const result = await projectApi.get("p1");

    expect(result.ok).toBe(false);
    expect(result.status).toBe(0);
    expect(result.error).toBe("Network error");
  });
});
