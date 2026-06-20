import { useSyncExternalStore } from "react";

import {
  listProjects,
  listRuns,
  subscribeRegistry,
  type ProjectRef,
  type RunRef,
} from "./registry";

/** Reactive view of the locally-known projects. */
export function useProjects(): ProjectRef[] {
  return useSyncExternalStore(subscribeRegistry, listProjects, () => []);
}

/** Reactive view of the locally-known runs. */
export function useRuns(): RunRef[] {
  return useSyncExternalStore(subscribeRegistry, listRuns, () => []);
}
