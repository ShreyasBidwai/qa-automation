import { AlertTriangle, CheckCircle2, Info, X, type LucideIcon } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

import { ToastContext, type ToastInput, type ToastTone } from "./useToast";

interface Toast extends ToastInput {
  id: string;
}

function defaultDuration(tone: ToastTone): number {
  return tone === "error" ? 8000 : 5000;
}

const TONE_STYLE: Record<
  ToastTone,
  { icon: LucideIcon; iconClass: string; borderClass: string }
> = {
  success: {
    icon: CheckCircle2,
    iconClass: "text-status-pass-solid",
    borderClass: "border-status-pass-border",
  },
  error: {
    icon: AlertTriangle,
    iconClass: "text-status-fail-solid",
    borderClass: "border-status-fail-border",
  },
  info: {
    icon: Info,
    iconClass: "text-status-info-solid",
    borderClass: "border-border",
  },
};

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const tone = toast.tone ?? "info";
  const { icon: Icon, iconClass, borderClass } = TONE_STYLE[tone];
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "animate-fade-in pointer-events-auto flex w-full items-start gap-3 rounded-lg border bg-surface p-3.5 shadow-xl",
        borderClass,
      )}
    >
      <Icon className={cn("h-5 w-5 shrink-0", iconClass)} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{toast.title}</p>
        {toast.description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{toast.description}</p>
        ) : null}
        {toast.action ? (
          <button
            type="button"
            onClick={() => {
              toast.action?.onClick();
              onDismiss();
            }}
            className="mt-2 text-xs font-semibold text-accent hover:underline"
          >
            {toast.action.label}
          </button>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-background"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * App-wide toasts (greenfield): a portal-rendered, accessible (role="status" /
 * aria-live="polite") stack in the bottom-right corner, auto-dismissing with a
 * manual close. Mounted once at the app root so any hook/component can `useToast()`
 * to surface a notification regardless of which page is active — the run/ingest
 * lifecycle hooks piggyback on this to announce completion even when the user has
 * navigated away from the page that started the work.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const nextId = useRef(0);

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback(
    (input: ToastInput) => {
      const id = `toast-${(nextId.current += 1)}`;
      const tone = input.tone ?? "info";
      const toast: Toast = { ...input, id, tone };
      setToasts((prev) => [...prev, toast]);
      const duration = input.durationMs ?? defaultDuration(tone);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), duration),
      );
    },
    [dismiss],
  );

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div
          aria-label="Notifications"
          className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
        >
          {toasts.map((toast) => (
            <ToastCard
              key={toast.id}
              toast={toast}
              onDismiss={() => dismiss(toast.id)}
            />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}
