import { Wordmark } from "@/components/Wordmark";

/** A calm full-screen splash while the session is being checked on load. */
export function AuthSplash() {
  return (
    <div
      className="flex min-h-screen items-center justify-center bg-background"
      role="status"
      aria-label="Loading"
    >
      <div className="flex flex-col items-center gap-3">
        <Wordmark size="lg" />
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    </div>
  );
}
