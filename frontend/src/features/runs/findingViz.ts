/**
 * Per-axis visual mappings for the run dashboard + finding detail. The severity
 * (sevViz) and history (histViz) colour maps are lifted VERBATIM from
 * "Polaris UI/Polaris Run Dashboard.dc.html" into centralized tokens (index.css):
 *   sevViz:  critical → red, major → amber, minor → slate
 *   histViz: new → blue, regression → amber, known → zinc, flaky → violet
 * (trustViz lives with the TrustMark, already verbatim.) Each returns token-backed
 * Tailwind classes — never raw hex; colour always travels with its label.
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
        pill: "bg-severity-critical-bg text-severity-critical-fg",
        fg: "text-severity-critical-fg",
        dot: "bg-severity-critical-dot",
      };
    case "major":
      return {
        label: "Major",
        pill: "bg-severity-major-bg text-severity-major-fg",
        fg: "text-severity-major-fg",
        dot: "bg-severity-major-dot",
      };
    case "minor":
      return {
        label: "Minor",
        pill: "bg-severity-minor-bg text-severity-minor-fg",
        fg: "text-severity-minor-fg",
        dot: "bg-severity-minor-dot",
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
  /** Label + dot colour. */
  text: string;
  /** The leading dot (same colour as the label). */
  dot: string;
  /** Soft background for the detail-panel history pill. */
  bg: string;
}

export function historyViz(status: string): HistoryViz {
  switch (status) {
    case "new":
      return {
        label: "New",
        text: "text-history-new-fg",
        dot: "bg-history-new-fg",
        bg: "bg-history-new-bg",
      };
    case "regression":
      return {
        label: "Regression",
        text: "text-history-regression-fg",
        dot: "bg-history-regression-fg",
        bg: "bg-history-regression-bg",
      };
    case "flaky":
      return {
        label: "Flaky",
        text: "text-history-flaky-fg",
        dot: "bg-history-flaky-fg",
        bg: "bg-history-flaky-bg",
      };
    case "known":
      return {
        label: "Known",
        text: "text-history-known-fg",
        dot: "bg-history-known-fg",
        bg: "bg-history-known-bg",
      };
    default:
      return {
        label: status,
        text: "text-muted-foreground",
        dot: "bg-status-neutral-solid",
        bg: "bg-status-neutral-bg",
      };
  }
}
