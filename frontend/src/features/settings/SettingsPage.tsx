import type { ReactNode } from "react";

import { PageShell } from "@/components/PageShell";
import { useToast } from "@/components/useToast";
import { useTheme, type Theme } from "@/lib/theme/useTheme";
import { cn } from "@/lib/utils";

const THEME_OPTIONS: Theme[] = ["light", "dark"];

function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** A labeled on/off switch (no `components/ui` primitive exists yet for this — a
 *  single-use `role="switch"` is simpler than introducing one for one call site). */
function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
        checked ? "bg-accent" : "bg-border",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}

/**
 * Real workspace preferences (mission item 5) — replaces the Settings placeholder.
 * Only residents that actually do something: the theme (ADR-0073, also reachable
 * from the top bar) and the toast-notification kill switch (ADR: none — a plain
 * on/off gate on the existing ToastProvider, see components/useToast.ts). No
 * placeholder rows for preferences that don't exist yet.
 */
export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const { notificationsEnabled, setNotificationsEnabled } = useToast();

  return (
    <PageShell
      maxWidth="max-w-[640px]"
      header={
        <div>
          <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
            Settings
          </h1>
          <p className="mt-0.5 text-[13px] text-status-neutral-solid">
            Preferences for how Polaris looks and notifies you on this device.
          </p>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <SettingsSection
          title="Appearance"
          description="Choose how Polaris looks on this device. Persisted here; also
            toggleable from the top bar."
        >
          <div
            role="radiogroup"
            aria-label="Theme"
            className="inline-flex rounded-lg border border-border bg-background p-0.5"
          >
            {THEME_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={theme === option}
                onClick={() => setTheme(option)}
                className={cn(
                  "rounded-[7px] px-4 py-1.5 text-[13px] font-medium capitalize transition-colors",
                  theme === option
                    ? "bg-accent-subtle text-accent"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {option}
              </button>
            ))}
          </div>
        </SettingsSection>

        <SettingsSection
          title="Notifications"
          description="Toast alerts when a run or model build finishes — on the
            current page or anywhere else in the app."
        >
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm text-foreground">Show toast notifications</span>
            <Switch
              checked={notificationsEnabled}
              onChange={setNotificationsEnabled}
              label="Show toast notifications"
            />
          </div>
        </SettingsSection>
      </div>
    </PageShell>
  );
}
