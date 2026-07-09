import { AlertTriangle } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { projectApi } from "@/lib/api/client";
import type { AiProvider } from "@/lib/api/types";
import { navigate } from "@/lib/router";

import { DbStateTierCard } from "./DbStateTierCard";
import { ProjectCredentialsCard } from "./ProjectCredentialsCard";
import { ProjectLoginConfigCard } from "./ProjectLoginConfigCard";
import { ProjectDocumentsCard } from "./ProjectDocumentsCard";
import { useProject } from "./useProject";

/** Project settings (#3b): a PATCH-backed edit form + a confirmed delete. */
export function EditProjectPage({ projectId }: { projectId: string }) {
  const { project, loading, error } = useProject(projectId);

  return (
    <PageShell scroll={false} maxWidth="max-w-[760px]">
      {/* Back-link + title stay put (ADR-0066); the settings body scrolls on its own. */}
      <div className="shrink-0">
        <Link
          to={`/projects/${projectId}`}
          className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        >
          ← {project?.name ?? "Project"}
        </Link>
        <div className="mb-7 mt-3">
          <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
            Project settings
          </h1>
          {project ? (
            <p className="mt-1.5 text-[13px] text-muted-foreground">{project.name}</p>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <Skeleton className="h-80 rounded-xl" />
        ) : error || !project ? (
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load this project"
            description="It may have been removed, or the service is briefly unavailable."
            actions={
              <Button asChild>
                <Link to="/projects">Back to projects</Link>
              </Button>
            }
          />
        ) : (
          <div className="space-y-7">
            <EditForm key={project.id} projectId={projectId} project={project} />
            <ProjectCredentialsCard key={`cred-${project.id}`} projectId={projectId} />
            <ProjectLoginConfigCard key={`login-${project.id}`} projectId={projectId} />
            <ProjectDocumentsCard key={`docs-${project.id}`} projectId={projectId} />
            <DbStateTierCard key={`tier-${project.id}`} projectId={projectId} />
            <DangerZone projectId={projectId} name={project.name} />
          </div>
        )}
      </div>
    </PageShell>
  );
}

function EditForm({
  projectId,
  project,
}: {
  projectId: string;
  project: {
    name: string;
    repo_url: string;
    app_url: string | null;
    stack?: string | null;
    ai_provider?: string | null;
  };
}) {
  const [name, setName] = useState(project.name);
  const [repoUrl, setRepoUrl] = useState(project.repo_url);
  const [appUrl, setAppUrl] = useState(project.app_url ?? "");
  const [stack, setStack] = useState(project.stack ?? "");
  const [aiProvider, setAiProvider] = useState<AiProvider>(
    project.ai_provider === "gemini" || project.ai_provider === "anthropic_api"
      ? project.ai_provider
      : "claude_cli",
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaved(false);
    if (!name.trim() || !repoUrl.trim()) {
      setError("Name and repository are required.");
      return;
    }
    setSaving(true);
    const result = await projectApi.update(projectId, {
      name: name.trim(),
      repo_url: repoUrl.trim(),
      app_url: appUrl.trim() || null,
      stack: stack.trim() || null,
      ai_provider: aiProvider,
    });
    setSaving(false);
    if (result.ok && result.data) {
      setSaved(true);
      return;
    }
    setError(result.error ?? "Could not save changes.");
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <div className="space-y-5 rounded-xl border border-border bg-surface p-6 shadow-card">
        <Field id="name" label="Project name" value={name} onChange={setName} />
        <Field
          id="repo_url"
          label="Repository URL"
          value={repoUrl}
          onChange={setRepoUrl}
          mono
        />
        <Field
          id="app_url"
          label="App URL"
          hint="The running app to test against. Optional."
          value={appUrl}
          onChange={setAppUrl}
          mono
        />
        <Field
          id="stack"
          label="Stack"
          hint="Auto-detected from the repo. Override if needed."
          value={stack}
          onChange={setStack}
          placeholder="Laravel"
        />
        <FieldSelect
          id="ai_provider"
          label="AI provider"
          hint="Which model generates this project's tests. The API key stays server-side (env)."
          value={aiProvider}
          onChange={(value) => setAiProvider(value as AiProvider)}
          options={[
            ["anthropic_api", "Claude (Anthropic API)"],
            ["claude_cli", "Claude (claude -p)"],
            ["gemini", "Gemini"],
          ]}
        />

        {error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p role="status" className="text-sm text-status-pass-fg">
            Changes saved.
          </p>
        ) : null}
      </div>

      <div className="mt-5 flex items-center justify-end gap-2.5">
        <Button
          type="button"
          variant="outline"
          onClick={() => navigate(`/projects/${projectId}`)}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}

function DangerZone({ projectId, name }: { projectId: string; name: string }) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setError(null);
    setDeleting(true);
    const result = await projectApi.remove(projectId);
    setDeleting(false);
    if (result.ok) {
      navigate("/projects");
      return;
    }
    setError(result.error ?? "Could not delete the project.");
  }

  return (
    <div className="rounded-xl border border-status-fail-border bg-status-fail-bg px-[22px] py-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-status-fail-fg">
            Delete project
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Removes <span className="font-medium text-foreground">{name}</span>, its
            runs, and all findings. This cannot be undone.
          </p>
        </div>
        {confirming ? (
          <div className="flex flex-none flex-wrap items-center gap-2.5">
            <span className="text-sm font-medium text-foreground">
              Delete this project?
            </span>
            <Button
              type="button"
              variant="outline"
              disabled={deleting}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              className="border-status-fail-solid bg-status-fail-solid hover:bg-status-fail-fg"
              disabled={deleting}
              onClick={remove}
            >
              {deleting ? "Deleting…" : "Yes, delete"}
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            className="flex-none border-status-fail-border text-status-fail-fg hover:bg-status-fail-bg"
            onClick={() => setConfirming(true)}
          >
            Delete project
          </Button>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-status-fail-fg">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  hint,
  placeholder,
  mono,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={mono ? "font-mono text-[13px]" : undefined}
      />
      {hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function FieldSelect({
  id,
  label,
  value,
  onChange,
  options,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={hint ? `${id}-hint` : undefined}
      >
        {options.map(([optValue, optLabel]) => (
          <option key={optValue} value={optValue}>
            {optLabel}
          </option>
        ))}
      </Select>
      {hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
