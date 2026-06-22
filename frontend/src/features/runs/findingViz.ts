/**
 * Per-axis visual mappings for the run dashboard + finding detail, in the new
 * design language (design brief). Each returns Tailwind class strings built from
 * the centralized tokens — never raw hex. Colour always travels with a word
 * (the label), so it never carries meaning alone.
 *
 * Kept apart from findingBadges.ts (which yields generic Badge levels): these are
 * the bespoke severity pill / dot and the history tag the hero screens use.
 */

export interface SeverityViz {
  label: string;
  /** Pill chrome (soft bg + same-family text). */
  pill: string;
  /** Standalone label colour (for the field grid). */
  fg: string;
  /** The leading status dot. */
  dot: string;
}

export function severityViz(severity: string): SeverityViz {
  switch (severity) {
    case "critical":
      return {
        label: "Critical",
        pill: "bg-status-fail-bg text-status-fail-fg",
        fg: "text-status-fail-fg",
        dot: "bg-status-fail-solid",
      };
    case "major":
      return {
        label: "Major",
        pill: "bg-status-flaky-bg text-status-flaky-fg",
        fg: "text-status-flaky-fg",
        dot: "bg-status-flaky-solid",
      };
    case "minor":
      return {
        label: "Minor",
        pill: "bg-status-neutral-bg text-status-neutral-fg",
        fg: "text-status-neutral-fg",
        dot: "bg-status-neutral-solid",
      };
    default:
      return {
        label: severity,
        pill: "bg-status-neutral-bg text-status-neutral-fg",
        fg: "text-status-neutral-fg",
        dot: "bg-status-neutral-solid",
      };
  }
}

export interface HistoryViz {
  label: string;
  /** Label colour. */
  text: string;
  /** The leading dot. */
  dot: string;
}

/** History tag: new = blue, regression = amber, known = zinc, flaky = amber. */
export function historyViz(status: string): HistoryViz {
  switch (status) {
    case "new":
      return { label: "New", text: "text-status-info-fg", dot: "bg-status-info-solid" };
    case "regression":
      return {
        label: "Regression",
        text: "text-status-flaky-fg",
        dot: "bg-status-flaky-solid",
      };
    case "flaky":
      return {
        label: "Flaky",
        text: "text-status-flaky-fg",
        dot: "bg-status-flaky-solid",
      };
    case "known":
      return {
        label: "Known",
        text: "text-muted-foreground",
        dot: "bg-status-neutral-solid",
      };
    default:
      return {
        label: status,
        text: "text-muted-foreground",
        dot: "bg-status-neutral-solid",
      };
  }
}
