import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthProvider } from "./lib/auth/AuthContext";
import { App } from "./App";
import "./index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element #root not found");
}

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ErrorBoundary>
  </StrictMode>,
);
