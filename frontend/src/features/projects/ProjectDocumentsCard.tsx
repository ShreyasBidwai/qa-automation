import { FileText, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { documentApi } from "@/lib/api/client";
import type { ProjectDocument } from "@/lib/api/types";

const DOC_KINDS: [string, string][] = [
  ["requirements", "Requirements"],
  ["api_contract", "API contract"],
  ["user_flow", "User flow"],
  ["acceptance_criteria", "Acceptance criteria"],
  ["other", "Other"],
];

/** Map the upload endpoint's status codes to a clear, honest message (ADR-0052). */
function uploadErrorMessage(status: number, fallback: string | undefined): string {
  switch (status) {
    case 413:
      return "That document is too large (max ~1 MB).";
    case 422:
      return "That document kind isn't supported.";
    case 400:
      return "The document must be non-empty UTF-8 text.";
    case 502:
      return "Embedding the document failed — please try again.";
    case 403:
      return "You need the manage-project role to attach documents.";
    default:
      return fallback ?? "Couldn't upload the document.";
  }
}

/**
 * Attach business documents to a project (requirements / API contracts / flows …)
 * — an upload control plus the list of attached documents with delete. Upload and
 * delete are MANAGE_PROJECT (the server 403s, surfaced honestly here); listing is
 * VIEW. Used on project settings and in the post-registration setup step.
 */
export function ProjectDocumentsCard({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<ProjectDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [docKind, setDocKind] = useState("requirements");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedTitle, setUploadedTitle] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void documentApi.list(projectId).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setDocs(result.data.items);
        setListError(null);
      } else {
        setListError(result.error ?? "Couldn't load documents.");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function onUpload() {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    setUploadedTitle(null);
    const result = await documentApi.upload(projectId, file, { docKind });
    setUploading(false);
    if (result.ok && result.data) {
      setDocs((current) => [result.data as ProjectDocument, ...current]);
      setUploadedTitle(result.data.title);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      return;
    }
    setUploadError(uploadErrorMessage(result.status, result.error));
  }

  async function onDelete(id: string) {
    setDeletingId(id);
    const result = await documentApi.remove(projectId, id);
    setDeletingId(null);
    if (result.ok) {
      setDocs((current) => current.filter((doc) => doc.id !== id));
      return;
    }
    setListError(
      result.status === 403
        ? "You need the manage-project role to remove documents."
        : (result.error ?? "Couldn't remove the document."),
    );
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <h2 className="text-[15px] font-semibold text-foreground">Documents</h2>
      <p className="mt-1 text-[13px] text-muted-foreground">
        Attach requirements, API contracts, or flows. Polaris embeds them so it can
        ground tests in what the app is supposed to do.
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="doc-file">Document file</Label>
          <input
            ref={fileInput}
            id="doc-file"
            type="file"
            accept=".txt,.md,.json,.yaml,.yml,text/*"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setUploadError(null);
              setUploadedTitle(null);
            }}
            className="block w-full text-[13px] text-muted-foreground file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-[13px] file:font-medium file:text-foreground hover:file:bg-surface-selected"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="doc-kind">Kind</Label>
          <Select
            id="doc-kind"
            value={docKind}
            onChange={(event) => setDocKind(event.target.value)}
            className="w-auto"
          >
            {DOC_KINDS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <Button type="button" onClick={onUpload} disabled={!file || uploading}>
          <Upload className="h-4 w-4" aria-hidden="true" />
          {uploading ? "Uploading…" : "Upload"}
        </Button>
      </div>

      <div aria-live="polite" className="mt-2 min-h-[1.25rem]">
        {uploadError ? (
          <p role="alert" className="text-[13px] text-status-fail-fg">
            {uploadError}
          </p>
        ) : uploadedTitle ? (
          <p className="text-[13px] text-status-pass-fg">
            Attached &ldquo;{uploadedTitle}&rdquo; and embedded it.
          </p>
        ) : null}
      </div>

      <div className="mt-4 border-t border-border-subtle pt-4">
        {loading ? (
          <p className="text-[13px] text-muted-foreground">Loading documents…</p>
        ) : listError ? (
          <p role="alert" className="text-[13px] text-status-fail-fg">
            {listError}
          </p>
        ) : docs.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            No documents attached yet.
          </p>
        ) : (
          <ul className="space-y-2">
            {docs.map((doc) => (
              <li
                key={doc.id}
                className="flex items-center justify-between gap-3 rounded-lg border border-border-subtle bg-background px-3 py-2.5"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <FileText
                    className="h-4 w-4 shrink-0 text-status-neutral-solid"
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-medium text-foreground">
                      {doc.title}
                    </p>
                    <p className="text-[11.5px] text-muted-foreground">
                      <span className="font-mono">{doc.doc_kind}</span> ·{" "}
                      {doc.chunk_count} {doc.chunk_count === 1 ? "chunk" : "chunks"}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove ${doc.title}`}
                  disabled={deletingId === doc.id}
                  onClick={() => onDelete(doc.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  {deletingId === doc.id ? "Removing…" : "Remove"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
