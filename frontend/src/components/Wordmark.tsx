import { cn } from "@/lib/utils";

/**
 * The Polaris wordmark — the name only, no icon (brand guardrail: NO star /
 * constellation / sci-fi / glyph standing in for a letter). The one justified
 * detail is a single letterform set in the indigo accent — the "i" — a quiet,
 * deliberate mark, not a gimmick. Sits in the sidebar (sm) and large on the
 * sign-in screen (lg).
 */
export function Wordmark({ size = "sm" }: { size?: "sm" | "lg" }) {
  return (
    <span
      className={cn(
        "font-semibold tracking-[-0.015em] text-foreground",
        size === "lg" ? "text-[32px]" : "text-[17px]",
      )}
    >
      Polar<span className="text-accent">i</span>s
    </span>
  );
}
