import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  documentApi: { list: vi.fn(), upload: vi.fn(), remove: vi.fn() },
}));

import { documentApi } from "@/lib/api/client";
import type { ProjectDocument } from "@/lib/api/types";

import { ProjectDocumentsCard } from "./ProjectDocumentsCard";

function doc(over: Partial<ProjectDocument>): ProjectDocument {
  return {
    id: "d1",
    title: "Spec.md",
    doc_kind: "requirements",
    chunk_count: 3,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

const empty = { ok: true, status: 200, data: { items: [], total: 0 } };

describe("ProjectDocumentsCard", () => {
  beforeEach(() => {
    vi.mocked(documentApi.list).mockReset();
    vi.mocked(documentApi.upload).mockReset();
    vi.mocked(documentApi.remove).mockReset();
    vi.mocked(documentApi.list).mockResolvedValue(empty);
  });

  it("lists attached documents", async () => {
    vi.mocked(documentApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [doc({})], total: 1 },
    });
    render(<ProjectDocumentsCard projectId="p1" />);
    expect(await screen.findByText("Spec.md")).toBeInTheDocument();
  });

  it("uploads a file and shows it with a success message", async () => {
    vi.mocked(documentApi.upload).mockResolvedValue({
      ok: true,
      status: 201,
      data: doc({ id: "d2", title: "requirements.txt" }),
    });
    render(<ProjectDocumentsCard projectId="p1" />);
    await screen.findByText("No documents attached yet.");

    const file = new File(["hello"], "requirements.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Document file"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Upload/ }));

    await waitFor(() =>
      expect(documentApi.upload).toHaveBeenCalledWith("p1", file, {
        docKind: "requirements",
      }),
    );
    expect(await screen.findByText(/Attached/)).toBeInTheDocument();
    expect(screen.getByText("requirements.txt")).toBeInTheDocument();
  });

  it("surfaces a 413 too-large error as a clear message", async () => {
    vi.mocked(documentApi.upload).mockResolvedValue({
      ok: false,
      status: 413,
      data: null,
      error: "document too large",
    });
    render(<ProjectDocumentsCard projectId="p1" />);
    await screen.findByText("No documents attached yet.");

    const file = new File(["x"], "big.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Document file"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Upload/ }));

    expect(await screen.findByText(/too large/)).toBeInTheDocument();
  });

  it("removes a document", async () => {
    vi.mocked(documentApi.list).mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [doc({})], total: 1 },
    });
    vi.mocked(documentApi.remove).mockResolvedValue({
      ok: true,
      status: 204,
      data: null,
    });
    render(<ProjectDocumentsCard projectId="p1" />);
    await screen.findByText("Spec.md");

    fireEvent.click(screen.getByRole("button", { name: "Remove Spec.md" }));

    await waitFor(() => expect(documentApi.remove).toHaveBeenCalledWith("p1", "d1"));
    await waitFor(() => expect(screen.queryByText("Spec.md")).toBeNull());
  });
});
