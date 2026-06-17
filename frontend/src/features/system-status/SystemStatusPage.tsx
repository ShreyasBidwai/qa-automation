import { RefreshCw } from "lucide-react";

import { StatusBadge } from "@/components/StatusBadge";
import { StatusRow } from "@/components/StatusRow";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { useSystemStatus } from "./useSystemStatus";

export function SystemStatusPage() {
  const { backend, database, overall, lastChecked, isChecking, refresh } =
    useSystemStatus();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            System status
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Live health of the control plane and its dependencies.
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={refresh} disabled={isChecking}>
          <RefreshCw
            className={cn("h-4 w-4", isChecking && "animate-spin")}
            aria-hidden="true"
          />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4 space-y-0">
          <div className="flex flex-col gap-1.5">
            <CardTitle>Services</CardTitle>
            <CardDescription>
              {lastChecked
                ? `Last checked ${lastChecked.toLocaleTimeString()}`
                : "Checking…"}
            </CardDescription>
          </div>
          <StatusBadge status={overall} />
        </CardHeader>
        <CardContent>
          <div className="divide-y divide-border">
            <StatusRow
              label="Backend API"
              description="FastAPI control plane · /healthz"
              status={backend}
            />
            <StatusRow
              label="Database"
              description="Postgres + pgvector · /readyz"
              status={database}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
