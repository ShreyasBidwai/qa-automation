import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { projectApi } from "@/lib/api/client";
import { navigate } from "@/lib/router";

import { ProjectCredentialsCard } from "./ProjectCredentialsCard";
import { ProjectDocumentsCard } from "./ProjectDocumentsCard";

interface FieldErrors {
  name?: string;
  repoUrl?: string;
}

/** Register a project: repo source + running app + auth config reference (#3). */
export function CreateProjectForm() {
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [appUrl, setAppUrl] = useState("");
  const [stack, setStack] = useState("");
  const [authConfigRef, setAuthConfigRef] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // After register we stay on a setup step so docs/credentials can be attached now,
  // while we have the new project id — rather than bouncing straight to the project.
  const [created, setCreated] = useState<{ id: string; name: string } | null>(null);

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    if (!name.trim()) next.name = "Enter a project name.";
    if (!repoUrl.trim()) next.repoUrl = "Enter the repository URL.";
    return next;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    const result = await projectApi.create({
      name: name.trim(),
      repo_url: repoUrl.trim(),
      app_url: appUrl.trim() || null,
      stack: stack.trim() || null,
      auth_config_ref: authConfigRef.trim() || null,
    });
    setSubmitting(false);

    if (result.ok && result.data) {
      // Move to the setup step (attach docs / configure the account) with the new id.
      setCreated({ id: result.data.id, name: result.data.name });
      return;
    }
    setSubmitError(result.error ?? "Could not register the project.");
  }

  if (created) {
    return (
      <div>
        <div className="rounded-xl border border-border bg-surface p-6 shadow-card">
          <h2 className="text-[15px] font-semibold text-foreground">
            Project registered
          </h2>
          <p className="mt-1 text-[13px] text-muted-foreground">
            <span className="font-medium text-foreground">{created.name}</span> is set
            up. Attach documents and configure the target account now, or skip — you can
            do both later in project settings.
          </p>
        </div>
        <div className="mt-5 space-y-7">
          <ProjectCredentialsCard projectId={created.id} />
          <ProjectDocumentsCard projectId={created.id} />
        </div>
        <div className="mt-5 flex items-center justify-end">
          <Button type="button" onClick={() => navigate(`/projects/${created.id}`)}>
            Go to project
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <div className="space-y-5 rounded-xl border border-border bg-surface p-6 shadow-card">
        <Field
          id="name"
          label="Project name"
          value={name}
          onChange={setName}
          placeholder="Acme Billing API"
          error={errors.name}
        />
        <Field
          id="repo_url"
          label="Repository URL"
          hint="A Git URL or a local path Polaris can read."
          value={repoUrl}
          onChange={setRepoUrl}
          placeholder="https://github.com/acme/billing.git"
          error={errors.repoUrl}
          mono
        />
        <Field
          id="app_url"
          label="App URL"
          hint="The running app to test against. Optional."
          value={appUrl}
          onChange={setAppUrl}
          placeholder="https://staging.acme.test"
          mono
        />
        <Field
          id="stack"
          label="Stack"
          hint="Auto-detected from the repo. Override if needed. Optional."
          value={stack}
          onChange={setStack}
          placeholder="Laravel"
        />
        <Field
          id="auth_config_ref"
          label="Auth config reference"
          hint="A reference to stored credentials — never a secret. Optional."
          value={authConfigRef}
          onChange={setAuthConfigRef}
          placeholder="vault://acme/checkout/test-user"
          mono
        />

        {submitError ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {submitError}
          </p>
        ) : null}
      </div>

      <div className="mt-5 flex items-center justify-end gap-2.5">
        <Button type="button" variant="outline" onClick={() => navigate("/projects")}>
          Cancel
        </Button>
        <Button type="submit" disabled={submitting}>
          {submitting ? "Registering…" : "Register project"}
        </Button>
      </div>
    </form>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  mono,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  hint?: string;
  error?: string;
  mono?: boolean;
}) {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={mono ? "font-mono text-[13px]" : undefined}
      />
      {error ? (
        <p id={`${id}-error`} className="text-xs text-status-fail-fg">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
