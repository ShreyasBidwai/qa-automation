import { useCallback, useEffect, useRef, useState } from "react";

import { healthApi } from "@/lib/api/client";

import {
  CHECKING,
  deriveBackendStatus,
  deriveDatabaseStatus,
  deriveOverallStatus,
  type StatusDescriptor,
} from "./status";

const POLL_INTERVAL_MS = 10_000;

export interface SystemStatus {
  backend: StatusDescriptor;
  database: StatusDescriptor;
  overall: StatusDescriptor;
  lastChecked: Date | null;
  isChecking: boolean;
  refresh: () => void;
}

/**
 * Container hook (Standards §5): owns data fetching/polling and exposes derived
 * presentational state. Polls every {@link POLL_INTERVAL_MS} and on demand,
 * guarding against overlapping checks.
 */
export function useSystemStatus(): SystemStatus {
  const [backend, setBackend] = useState<StatusDescriptor>(CHECKING);
  const [database, setDatabase] = useState<StatusDescriptor>(CHECKING);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const inFlight = useRef(false);

  const runChecks = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setIsChecking(true);
    try {
      const [liveness, readiness] = await Promise.all([
        healthApi.liveness(),
        healthApi.readiness(),
      ]);
      setBackend(deriveBackendStatus(liveness));
      setDatabase(deriveDatabaseStatus(readiness));
      setLastChecked(new Date());
    } finally {
      inFlight.current = false;
      setIsChecking(false);
    }
  }, []);

  useEffect(() => {
    void runChecks();
    const id = setInterval(() => void runChecks(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [runChecks]);

  return {
    backend,
    database,
    overall: deriveOverallStatus(backend, database),
    lastChecked,
    isChecking,
    refresh: () => void runChecks(),
  };
}
