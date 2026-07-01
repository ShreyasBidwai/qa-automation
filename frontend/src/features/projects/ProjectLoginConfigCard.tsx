import { LogIn } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authConfigApi } from "@/lib/api/client";
import type { AuthConfigStatus, AuthConfigUpsertBody } from "@/lib/api/types";

/**
 * Login config for the authenticated crawl (ADR-0056): WHERE runs sign in (a login
 * URL) plus optional DOM-selector overrides for apps whose fields don't match the
 * cross-stack defaults. Carries NO secret — the account/password/TOTP seed live in
 * the Target-account card (the vault). Paired with credentials, this lets Polaris
 * crawl behind the login gate. Mutations need the manage-project role.
 */
const SELECTOR_FIELDS = [
  ["username_selector", "Username / email field"],
  ["password_selector", "Password field"],
  ["submit_selector", "Submit button"],
  ["otp_selector", "OTP / 2FA field"],
  ["otp_submit_selector", "OTP submit button"],
  ["success_selector", "Signed-in indicator"],
] as const;

type SelectorKey = (typeof SELECTOR_FIELDS)[number][0];

export function ProjectLoginConfigCard({ projectId }: { projectId: string }) {
  const [loginUrl, setLoginUrl] = useState("");
  const [selectors, setSelectors] = useState<Record<SelectorKey, string>>(
    {} as Record<SelectorKey, string>,
  );
  const [configured, setConfigured] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function seed(data: AuthConfigStatus) {
    setLoginUrl(data.login_url ?? "");
    setConfigured(data.configured);
    const next = {} as Record<SelectorKey, string>;
    for (const [key] of SELECTOR_FIELDS) next[key] = data[key] ?? "";
    setSelectors(next);
    if (SELECTOR_FIELDS.some(([key]) => data[key])) setShowAdvanced(true);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void authConfigApi.get(projectId).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) seed(result.data);
      else if (result.status !== 403)
        setError(result.error ?? "Couldn't load the login config.");
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function onSave() {
    setError(null);
    setSaved(false);
    if (!loginUrl.trim()) {
      setError("Enter the login page URL.");
      return;
    }
    setSaving(true);
    const body: AuthConfigUpsertBody = { login_url: loginUrl.trim() };
    for (const [key] of SELECTOR_FIELDS) {
      const value = selectors[key]?.trim();
      if (value) body[key] = value;
    }
    const result = await authConfigApi.put(projectId, body);
    setSaving(false);
    if (result.ok && result.data) {
      seed(result.data);
      setSaved(true);
      return;
    }
    setError(
      result.status === 403
        ? "You need the manage-project role to set the login config."
        : (result.error ?? "Couldn't save the login config."),
    );
  }

  async function onClear() {
    setError(null);
    setSaved(false);
    setSaving(true);
    const result = await authConfigApi.remove(projectId);
    setSaving(false);
    if (result.ok || result.status === 404) {
      setLoginUrl("");
      setSelectors({} as Record<SelectorKey, string>);
      setConfigured(false);
      setShowAdvanced(false);
      return;
    }
    setError(
      result.status === 403
        ? "You need the manage-project role to clear the login config."
        : (result.error ?? "Couldn't clear the login config."),
    );
  }

  if (loading) {
    return (
      <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
        <p className="text-[13px] text-muted-foreground">Loading login config…</p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <div className="flex items-center gap-2">
        <LogIn className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <h2 className="text-[15px] font-semibold text-foreground">Login page</h2>
      </div>
      <p className="mt-1 text-[13px] text-muted-foreground">
        Where runs sign in so Polaris can crawl behind the gate. Uses the account from
        the card above. No secret is entered here.
      </p>

      <div className="mt-4 space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="login-url">Login URL</Label>
          <Input
            id="login-url"
            type="url"
            inputMode="url"
            value={loginUrl}
            onChange={(event) => setLoginUrl(event.target.value)}
            placeholder="https://app.example.com/login"
          />
        </div>

        <button
          type="button"
          onClick={() => setShowAdvanced((value) => !value)}
          aria-expanded={showAdvanced}
          className="text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          {showAdvanced ? "Hide advanced selectors" : "Advanced selectors (optional)"}
        </button>

        {showAdvanced ? (
          <div className="space-y-3 rounded-lg border border-border-subtle bg-background p-3">
            <p className="text-[11.5px] text-muted-foreground">
              CSS selectors for the login form. Leave blank to use the cross-stack
              defaults.
            </p>
            {SELECTOR_FIELDS.map(([key, label]) => (
              <div key={key} className="space-y-1.5">
                <Label htmlFor={`sel-${key}`}>{label}</Label>
                <Input
                  id={`sel-${key}`}
                  type="text"
                  value={selectors[key] ?? ""}
                  onChange={(event) =>
                    setSelectors((prev) => ({ ...prev, [key]: event.target.value }))
                  }
                  placeholder="default"
                  className="font-mono text-[12px]"
                />
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="mt-3 text-[13px] text-status-fail-fg">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p role="status" className="mt-3 text-[13px] text-status-pass-fg">
          Login config saved.
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-2.5">
        <Button type="button" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {configured ? (
          <Button type="button" variant="ghost" disabled={saving} onClick={onClear}>
            Clear
          </Button>
        ) : null}
      </div>
    </section>
  );
}
