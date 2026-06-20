/**
 * One mapping for run mode, regardless of source. The runs-list endpoint returns
 * the persisted `Run.mode` ("B" / "C"); the run-create form uses "mode_b" /
 * "mode_c". This normalizes both to a single human label so the UI is consistent
 * everywhere mode is shown.
 */
export function modeLabel(mode: string): string {
  switch (mode) {
    case "B":
    case "mode_b":
      return "Autonomous (Mode B)";
    case "C":
    case "mode_c":
      return "Natural language (Mode C)";
    default:
      return mode;
  }
}
