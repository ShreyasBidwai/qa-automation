import { afterEach, describe, expect, it, vi } from "vitest";

import { findingApi, projectApi, runApi } from "./client";

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

  it("GET /projects?limit&offset builds the list URL", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, limit: 20, offset: 40 }),
    );
    await projectApi.list({ limit: 20, offset: 40 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/projects?limit=20&offset=40");
  });

  it("GET /projects/:id/runs builds the scoped list URL", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, limit: 10, offset: 0 }),
    );
    await runApi.list("p1", { limit: 10, offset: 0 });
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/projects/p1/runs?limit=10&offset=0",
    );
  });

  it("PATCH /projects/:id sends the partial update", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        id: "p1",
        name: "Renamed",
        slug: "demo-1",
        repo_url: "https://git/x.git",
        app_url: null,
        auth_config_ref: null,
        stack: "Laravel",
        created_at: "2026-01-01T00:00:00Z",
      }),
    );

    const result = await projectApi.update("p1", { name: "Renamed", stack: "Laravel" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects/p1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ name: "Renamed", stack: "Laravel" });
    expect(result.data?.name).toBe("Renamed");
  });

  it("DELETE /projects/:id soft-deletes (204 → ok:true)", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204, json: async () => null });

    const result = await projectApi.remove("p1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/projects/p1");
    expect(init.method).toBe("DELETE");
    expect(result.ok).toBe(true);
  });

  it("GET /findings builds the global inbox URL", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, limit: 25, offset: 0 }),
    );
    await findingApi.listOpen({ limit: 25, offset: 0 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/findings?limit=25&offset=0");
  });

  it("GET /projects/:id/findings builds the project inbox URL", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }),
    );
    await findingApi.listForProject("p1", { limit: 50, offset: 0 });
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/projects/p1/findings?limit=50&offset=0",
    );
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
