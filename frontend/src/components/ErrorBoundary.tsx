import { Component, type ErrorInfo, type ReactNode } from "react";

import { GenericErrorPage } from "@/components/GenericErrorPage";

interface State {
  error: Error | null;
}

/**
 * Catches render-time crashes anywhere below it and shows the on-brand generic
 * error page instead of a blank screen (design brief: a generic error page,
 * first-class). Wraps the whole app in main.tsx.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface to the console for now; a real reporter wires in later.
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return <GenericErrorPage />;
    }
    return this.props.children;
  }
}
