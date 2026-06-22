import { cn } from "@/lib/utils";

/**
 * The Polaris wordmark — the name only, no icon (brand guardrail: NO star /
 * constellation / sci-fi / glyph standing in for a letter). The one justified
 * detail is a single letterform set in the indigo accent — ONLY the "i".
 * Locked spec (Polaris Wordmark.dc.html): Inter 600 at −0.02em tracking; the
 * accented "i" uses the primary indigo (#4F46E5), or #818CF8 on a dark surface.
 * `size` sets the default scale; `className` overrides it (e.g. the auth panel).
 */
export function Wordmark({
  size = "sm",
  tone = "default",
  className,
}: {
  size?: "sm" | "lg";
  tone?: "default" | "reversed";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-semibold tracking-[-0.02em]",
        tone === "reversed" ? "text-surface" : "text-foreground",
        size === "lg" ? "text-[32px]" : "text-[17px]",
        className,
      )}
    >
      Polar
      <span className={tone === "reversed" ? "text-accent-on-dark" : "text-accent"}>
        i
      </span>
      s
    </span>
  );
}
