import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Loader2,
  OctagonAlert,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { StatusDescriptor, StatusLevel } from "@/features/system-status/status";
import { cn } from "@/lib/utils";

// Every level carries a distinct icon AND label, so status is never signalled
// by colour alone (PRD §9, accessibility). `error` (couldn't run) uses its own
// octagon so it never looks like an `fail` X (a real failure).
const ICON_BY_LEVEL: Record<StatusLevel, LucideIcon> = {
  pass: CheckCircle2,
  fail: XCircle,
  error: OctagonAlert,
  flaky: AlertTriangle,
  info: Loader2,
  neutral: CircleDashed,
};

export function StatusBadge({ status }: { status: StatusDescriptor }) {
  const Icon = ICON_BY_LEVEL[status.level];
  return (
    <Badge level={status.level}>
      <Icon
        className={cn("h-3.5 w-3.5", status.level === "info" && "animate-spin")}
        aria-hidden="true"
      />
      {status.label}
    </Badge>
  );
}
