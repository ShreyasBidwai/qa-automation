import { AppShell } from "@/components/AppShell";
import { SystemStatusPage } from "@/features/system-status/SystemStatusPage";

export function App() {
  return (
    <AppShell>
      <SystemStatusPage />
    </AppShell>
  );
}
