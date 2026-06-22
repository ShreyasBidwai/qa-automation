import { AlertTriangle } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { projectApi } from "@/lib/api/client";
import { navigate } from "@/lib/router";

import { useProject } from "./useProject";

/** Edit a project's settings (#3b), with a quiet danger zone to delete it. */
export function EditProjectPage({ projectId }: { projectId: string }) {
  const { project, loading, error } = useProject(projectId);

  return (
    <>
      <PageHeader
        eyebrow={
          <Link to={`/projects/${projectId}`}>{project?.name ?? "Project"}</Link>
        }
        title="Edit project"
      />
      <main className="flex-1 px-6 py-8">
        {loading ? (
          <Skeleton className="h-80 max-w-xl rounded-xl" />
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
          <div className="max-w-xl space-y-6">
            <EditForm key={project.id} projectId={projectId} project={project} />
            <DangerZone projectId={projectId} name={project.name} />
          </div>
        )}
      </main>
    </>
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
  };
}) {
  const [name, setName] = useState(project.name);
  const [repoUrl, setRepoUrl] = useState(project.repo_url);
  const [appUrl, setAppUrl] = useState(project.app_url ?? "");
  const [stack, setStack] = useState(project.stack ?? "");
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
    });
    setSaving(false);
    if (result.ok && result.data) {
      setSaved(true);
      return;
    }
    setError(result.error ?? "Could not save changes.");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Settings</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="space-y-5">
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

          <div className="flex items-center gap-3 pt-1">
            <Button type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => navigate(`/projects/${projectId}`)}
            >
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
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
    <Card className="border-status-fail-solid/40">
      <CardHeader>
        <CardTitle className="text-status-fail-fg">Danger zone</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Delete <span className="font-medium text-foreground">{name}</span>. Its runs
          and findings are hidden from Polaris; this can&rsquo;t be undone here.
        </p>
        {confirming ? (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium text-foreground">
              Delete this project?
            </span>
            <Button
              type="button"
              variant="outline"
              className="border-status-fail-solid text-status-fail-fg hover:bg-status-fail-bg"
              disabled={deleting}
              onClick={remove}
            >
              {deleting ? "Deleting…" : "Yes, delete"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={deleting}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            className="border-status-fail-solid text-status-fail-fg hover:bg-status-fail-bg"
            onClick={() => setConfirming(true)}
          >
            Delete project
          </Button>
        )}
        {error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
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
