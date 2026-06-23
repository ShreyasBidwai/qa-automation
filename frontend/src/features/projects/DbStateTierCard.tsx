import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { projectApi } from "@/lib/api/client";
import type { DbStateTier } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const TIERS: { value: DbStateTier; title: string; description: string }[] = [
  {
    value: "off",
    title: "Off",
    description: "No database-state testing. Runs never touch the database directly.",
  },
  {
    value: "read_only",
    title: "Read-only",
    description:
      "Polaris may read the database to make assertions (SELECT only). It never writes, so it is safe against any target.",
  },
  {
    value: "full",
    title: "Full — write-capable",
    description:
      "Polaris may also write to the database as part of a test. Safe only against a disposable, non-production target.",
  },
];

/**
 * The per-project DB-state testing tier (B10, ADR-0043): off / read_only / full.
 * Reads the current tier (GET, needs VIEW) and changes it (PUT, needs
 * MANAGE_PROJECT). The project payload doesn't expose the caller's role, so — like
 * the edit form and danger zone on this screen — the control is shown to everyone
 * who can view the project and the server's 403 is the real boundary, surfaced
 * honestly. The `full` write caveat is stated plainly and never hidden.
 */
export function DbStateTierCard({ projectId }: { projectId: string }) {
  const [tier, setTier] = useState<DbStateTier | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<DbStateTier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    void projectApi.getDbStateTier(projectId).then((result) => {
      if (cancelled) return;
      setLoading(false);
      if (result.ok && result.data) setTier(result.data.tier);
      else setLoadError(result.error ?? "Couldn't load the testing tier.");
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function choose(next: DbStateTier) {
    if (next === tier || saving !== null) return;
    setError(null);
    setSaved(false);
    setSaving(next);
    const result = await projectApi.setDbStateTier(projectId, { tier: next });
    setSaving(null);
    if (result.ok && result.data) {
      setTier(result.data.tier);
      setSaved(true);
      return;
    }
    // The API is authoritative; surface its refusal plainly (403 = not allowed).
    if (result.status === 403) {
      setError(
        "You don't have permission to change this. Ask a project owner or admin.",
      );
    } else {
      setError(result.error ?? "Couldn't change the testing tier.");
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <h2 className="text-sm font-semibold text-foreground">Database-state testing</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        How far a run may go when checking your data layer directly — asserting on the
        rows in the target database, not just the app’s responses.
      </p>

      {loading ? (
        <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
      ) : loadError ? (
        <p role="alert" className="mt-4 text-sm text-status-fail-fg">
          {loadError}
        </p>
      ) : (
        <>
          <div
            role="radiogroup"
            aria-label="DB-state testing tier"
            className="mt-4 space-y-2.5"
          >
            {TIERS.map((option) => {
              const selected = tier === option.value;
              return (
                <label
                  key={option.value}
                  className={cn(
                    "flex cursor-pointer gap-3 rounded-lg border p-3.5 transition-colors",
                    selected
                      ? "border-accent bg-accent-subtle"
                      : "border-border hover:bg-background",
                    saving !== null && "opacity-70",
                  )}
                >
                  <input
                    type="radio"
                    name="db-state-tier"
                    value={option.value}
                    checked={selected}
                    disabled={saving !== null}
                    onChange={() => choose(option.value)}
                    className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                  />
                  <span className="min-w-0">
                    <span
                      className={cn(
                        "block text-sm font-medium",
                        selected ? "text-accent" : "text-foreground",
                      )}
                    >
                      {option.title}
                    </span>
                    <span className="mt-0.5 block text-[13px] leading-relaxed text-muted-foreground">
                      {option.description}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>

          <div className="mt-3 flex items-start gap-2.5 rounded-lg bg-status-flaky-bg px-3.5 py-3 text-[13px] leading-relaxed text-status-flaky-fg">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <p>
              <span className="font-semibold">Full writes to the target database.</span>{" "}
              Only ever point it at a disposable, non-production environment — never
              your production data. Polaris also refuses write-tests against a target it
              detects as production, but you are the first line of defence.
            </p>
          </div>

          {error ? (
            <p role="alert" className="mt-3 text-sm text-status-fail-fg">
              {error}
            </p>
          ) : null}
          {saved ? (
            <p role="status" className="mt-3 text-sm text-status-pass-fg">
              Testing tier updated.
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
