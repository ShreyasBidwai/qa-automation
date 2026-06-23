/**
 * The overall project status (backend ProjectSummary.derive_status, ADR-0045):
 * never_run → errored → action_needed → passing. Each maps to a tokenized pill
 * (Polaris Projects.dc.html status pill: a dot + a coloured label on a tint).
 * Colour is always paired with the word, never the sole signal.
 */
export interface ProjectStatusViz {
  label: string;
  dot: string; // background class for the leading dot
  text: string; // foreground class
  bg: string; // pill background class
}

export function projectStatusViz(status: string | undefined): ProjectStatusViz {
  switch (status) {
    case "passing":
      return {
        label: "Passing",
        dot: "bg-status-pass-solid",
        text: "text-status-pass-fg",
        bg: "bg-status-pass-bg",
      };
    case "action_needed":
      return {
        label: "Action needed",
        dot: "bg-status-flaky-solid",
        text: "text-status-flaky-fg",
        bg: "bg-status-flaky-bg",
      };
    case "errored":
      return {
        label: "Errored",
        dot: "bg-status-fail-solid",
        text: "text-status-fail-fg",
        bg: "bg-status-fail-bg",
      };
    default: // never_run (and any unknown/absent value)
      return {
        label: "Never run",
        dot: "bg-status-neutral-solid",
        text: "text-status-neutral-fg",
        bg: "bg-status-neutral-bg",
      };
  }
}
