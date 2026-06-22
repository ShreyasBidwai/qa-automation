import { cn } from "@/lib/utils";

/**
 * The Polaris wordmark — the name only, no icon (brand guardrail: NO star /
 * constellation / sci-fi / glyph standing in for a letter). The one justified
 * detail is a single letterform set in the indigo accent — the "i". Locked spec
 * (Polaris Wordmark.dc.html): Inter 600 at −0.02em tracking, the indigo "i" the
 * same indigo used for the primary action and active nav, and nowhere else.
 * `size` sets the default scale; `className` overrides it for bespoke contexts
 * (e.g. the auth brand panel at 30px).
 */
export function Wordmark({
  size = "sm",
  className,
}: {
  size?: "sm" | "lg";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-semibold tracking-[-0.02em] text-foreground",
        size === "lg" ? "text-[32px]" : "text-[17px]",
        className,
      )}
    >
      Polar<span className="text-accent">i</span>s
    </span>
  );
}
