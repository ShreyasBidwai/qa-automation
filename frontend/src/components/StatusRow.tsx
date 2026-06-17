import type { StatusDescriptor } from "@/features/system-status/status";

import { StatusBadge } from "./StatusBadge";

interface StatusRowProps {
  label: string;
  description: string;
  status: StatusDescriptor;
}

export function StatusRow({ label, description, status }: StatusRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-3.5">
      <div className="flex flex-col">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">{description}</span>
      </div>
      <StatusBadge status={status} />
    </div>
  );
}
