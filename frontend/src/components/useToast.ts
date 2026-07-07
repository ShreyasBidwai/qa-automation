import { createContext, useContext } from "react";

export type ToastTone = "info" | "success" | "error";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  action?: ToastAction;
  /** Auto-dismiss delay. Defaults to 8s for errors (more to read), 5s otherwise. */
  durationMs?: number;
}

export interface ToastContextValue {
  notify: (toast: ToastInput) => void;
  /** Whether toasts are shown at all — the Settings "Notifications" preference
   *  (persisted). Exposed here (rather than a separate provider) so there is one
   *  place that decides whether a notification ever reaches the screen. */
  notificationsEnabled: boolean;
  setNotificationsEnabled: (enabled: boolean) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

/** Fire a toast from anywhere in the app. Throws outside a `ToastProvider` — the
 *  same "must be inside its provider" contract as `useAuth`. */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}
