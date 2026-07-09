import { ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { credentialApi } from "@/lib/api/client";
import type { CredentialMode } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Target-account credentials for a project (ADR-0053): choose whether runs use a
 * specific, user-provided account or let Polaris provision its own. The account
 * secret is WRITE-ONLY — GET never returns it, so a stored password is shown only
 * as "saved" (with the identifier) and is replaced, never displayed. The plaintext
 * is held client-side only while editing and cleared right after a successful save.
 * All operations are MANAGE_PROJECT; a 403 is surfaced honestly.
 */
export function ProjectCredentialsCard({ projectId }: { projectId: string }) {
  const [mode, setMode] = useState<CredentialMode>("polaris_creates");
  const [identifier, setIdentifier] = useState("");
  const [secret, setSecret] = useState(""); // write-only; never seeded from GET
  const [totpSecret, setTotpSecret] = useState(""); // write-only; never seeded
  const [hasCredentials, setHasCredentials] = useState(false);
  const [hasTotp, setHasTotp] = useState(false);
  const [editing, setEditing] = useState(false);

  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void credentialApi.get(projectId).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setMode(
          result.data.mode === "specific_account"
            ? "specific_account"
            : "polaris_creates",
        );
        setIdentifier(result.data.identifier ?? "");
        setHasCredentials(result.data.has_credentials);
        setHasTotp(result.data.has_totp);
        setEditing(false);
      } else if (result.status === 403) {
        setForbidden(true);
      } else {
        setError(result.error ?? "Couldn't load credentials.");
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  function chooseMode(next: CredentialMode) {
    setMode(next);
    setError(null);
    setSaved(false);
    setSecret(""); // never carry a typed secret across a mode switch
    setTotpSecret("");
    // A specific account with nothing stored opens straight into the edit fields.
    setEditing(next === "specific_account" && !hasCredentials);
  }

  async function refresh() {
    const result = await credentialApi.get(projectId);
    if (result.ok && result.data) {
      setMode(
        result.data.mode === "specific_account"
          ? "specific_account"
          : "polaris_creates",
      );
      setIdentifier(result.data.identifier ?? "");
      setHasCredentials(result.data.has_credentials);
      setHasTotp(result.data.has_totp);
    }
  }

  async function onSave() {
    setError(null);
    setSaved(false);
    if (mode === "specific_account") {
      if (!identifier.trim()) {
        setError("Enter the account's username, email, or mobile.");
        return;
      }
      if (!secret.trim()) {
        setError("Enter the account password.");
        return;
      }
    }
    setSaving(true);
    const result = await credentialApi.put(projectId, {
      mode,
      ...(mode === "specific_account"
        ? {
            identifier: identifier.trim(),
            secret,
            // Only send the TOTP seed when the operator typed one; omitting it
            // PRESERVES any stored seed (the backend replace-preserves it).
            ...(totpSecret.trim() ? { totp_secret: totpSecret.trim() } : {}),
          }
        : {}),
    });
    setSecret(""); // drop the plaintext as soon as it's been sent
    setTotpSecret("");
    setSaving(false);
    if (result.ok) {
      setEditing(false);
      setSaved(true);
      await refresh();
      return;
    }
    setError(
      result.status === 403
        ? "You need the manage-project role to set credentials."
        : (result.error ?? "Couldn't save credentials."),
    );
  }

  async function onRemove() {
    setError(null);
    setSaved(false);
    setSaving(true);
    const result = await credentialApi.remove(projectId);
    setSaving(false);
    if (result.ok || result.status === 404) {
      setMode("polaris_creates");
      setIdentifier("");
      setSecret("");
      setTotpSecret("");
      setHasCredentials(false);
      setHasTotp(false);
      setEditing(false);
      return;
    }
    setError(
      result.status === 403
        ? "You need the manage-project role to clear credentials."
        : (result.error ?? "Couldn't clear credentials."),
    );
  }

  if (loading) {
    return (
      <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
        <p className="text-[13px] text-muted-foreground">Loading credentials…</p>
      </section>
    );
  }

  if (forbidden) {
    return (
      <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
        <h2 className="text-[15px] font-semibold text-foreground">Target account</h2>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Managing target-account credentials requires the manage-project role.
        </p>
      </section>
    );
  }

  const showEditableFields =
    mode === "specific_account" && (editing || !hasCredentials);
  const showSavedState = mode === "specific_account" && hasCredentials && !editing;
  // In Polaris-creates mode, only offer Save when there's a stored account to clear.
  const showSave = showEditableFields || (mode === "polaris_creates" && hasCredentials);

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <h2 className="text-[15px] font-semibold text-foreground">Target account</h2>
      <p className="mt-1 text-[13px] text-muted-foreground">
        How runs sign in to the app under test.
      </p>

      <div className="mt-4 space-y-2.5">
        <ModeOption
          selected={mode === "polaris_creates"}
          onSelect={() => chooseMode("polaris_creates")}
          title="Let Polaris create a test account"
          description="Polaris provisions a fresh account for each run. No secret stored."
        />
        <ModeOption
          selected={mode === "specific_account"}
          onSelect={() => chooseMode("specific_account")}
          title="Test a specific account"
          description="Use a real account you provide. Its password is encrypted at rest."
        />
      </div>

      {showSavedState ? (
        <div className="mt-4 rounded-lg border border-border-subtle bg-background px-3.5 py-3">
          <div className="flex items-center gap-2">
            <ShieldCheck
              className="h-4 w-4 shrink-0 text-status-pass-fg"
              aria-hidden="true"
            />
            <p className="text-[13px] text-foreground">
              Credentials saved — testing as{" "}
              <span className="font-medium">{identifier || "the saved account"}</span>.
            </p>
          </div>
          <p className="mt-1 pl-6 text-[11.5px] text-muted-foreground">
            The password is stored securely and never shown.
            {hasTotp ? " 2FA (TOTP) is configured — runs sign in unattended." : ""}
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2 pl-6">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setEditing(true);
                setSecret("");
                setSaved(false);
              }}
            >
              Replace credentials
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={saving}
              onClick={onRemove}
            >
              Remove
            </Button>
          </div>
        </div>
      ) : null}

      {showEditableFields ? (
        <div className="mt-4 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="cred-identifier">Username, email, or mobile</Label>
            <Input
              id="cred-identifier"
              type="text"
              autoComplete="username"
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder="qa-user@example.com or a username"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cred-secret">Password</Label>
            <Input
              id="cred-secret"
              type="password"
              autoComplete="new-password"
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
              placeholder={hasCredentials ? "Enter a new password" : "Account password"}
            />
            <p className="text-[11.5px] text-muted-foreground">
              Write-only — it&rsquo;s encrypted on save and never displayed again.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cred-totp">
              TOTP secret{" "}
              <span className="font-normal text-muted-foreground">
                (optional — for 2FA)
              </span>
            </Label>
            <Input
              id="cred-totp"
              type="password"
              autoComplete="off"
              value={totpSecret}
              onChange={(event) => setTotpSecret(event.target.value)}
              placeholder={
                hasTotp
                  ? "2FA configured — enter to replace"
                  : "Authenticator seed (base32)"
              }
              className="font-mono"
            />
            <p className="text-[11.5px] text-muted-foreground">
              The authenticator-app shared secret. Runs generate the 2FA code
              automatically so login is unattended. Encrypted; leave blank to keep the
              stored one.
            </p>
          </div>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-[13px] text-status-fail-fg">
          {error}
        </p>
      ) : null}
      {/* The saved-state block already says "saved"; only show this for the other
       *  cases (Polaris-creates, or a fresh specific account) to avoid repetition. */}
      {saved && !showSavedState ? (
        <p role="status" className="mt-3 text-[13px] text-status-pass-fg">
          Credentials saved.
        </p>
      ) : null}

      {showSave ? (
        <div className="mt-4 flex items-center gap-2.5">
          <Button type="button" onClick={onSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          {showEditableFields && hasCredentials ? (
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={() => {
                setEditing(false);
                setSecret("");
                setError(null);
              }}
            >
              Cancel
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ModeOption({
  selected,
  onSelect,
  title,
  description,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  description: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border p-3",
        selected ? "border-accent bg-accent-subtle" : "border-border bg-surface",
      )}
    >
      <input
        type="radio"
        name="credential-mode"
        checked={selected}
        onChange={onSelect}
        className="mt-0.5 h-4 w-4 shrink-0 text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-foreground">{title}</span>
        <span className="block text-xs text-muted-foreground">{description}</span>
      </span>
    </label>
  );
}
