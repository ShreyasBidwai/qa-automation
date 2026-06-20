import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { projectApi } from "@/lib/api/client";
import type { Project } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { rememberProject } from "@/lib/registry";

interface FieldErrors {
  name?: string;
  repoUrl?: string;
}

/** Register a project: repo source + running app + auth config reference. */
export function CreateProjectForm() {
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [appUrl, setAppUrl] = useState("");
  const [authConfigRef, setAuthConfigRef] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
      auth_config_ref: authConfigRef.trim() || null,
    });
    setSubmitting(false);

    if (result.ok && result.data) {
      const project: Project = result.data;
      rememberProject({
        id: project.id,
        name: project.name,
        slug: project.slug,
        createdAt: project.created_at,
      });
      navigate(`/projects/${project.id}`);
      return;
    }
    setSubmitError(result.error ?? "Could not register the project.");
  }

  return (
    <form onSubmit={onSubmit} noValidate className="max-w-xl space-y-5">
      <Field
        id="name"
        label="Project name"
        value={name}
        onChange={setName}
        placeholder="Checkout service"
        error={errors.name}
      />
      <Field
        id="repo_url"
        label="Repository URL"
        value={repoUrl}
        onChange={setRepoUrl}
        placeholder="https://github.com/acme/checkout.git"
        error={errors.repoUrl}
        mono
      />
      <Field
        id="app_url"
        label="App URL"
        hint="The running app to test against. Optional."
        value={appUrl}
        onChange={setAppUrl}
        placeholder="https://staging.acme.com"
        mono
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

      <div className="flex items-center gap-3 pt-1">
        <Button type="submit" disabled={submitting}>
          {submitting ? "Registering…" : "Register project"}
        </Button>
        <Button type="button" variant="ghost" onClick={() => navigate("/projects")}>
          Cancel
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
