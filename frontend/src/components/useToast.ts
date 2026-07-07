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
