import { Drawer } from "@/components/Drawer";
import type { Finding } from "@/lib/api/types";

import { FindingDetail } from "./FindingDetail";

/**
 * The finding detail in a right-side drawer — used by the findings inbox (the run
 * dashboard renders the same FindingDetail inline as its master-detail panel).
 */
export function FindingDrawer({
  finding,
  runId,
  onClose,
  onTriaged,
}: {
  finding: Finding | null;
  runId: string;
  onClose: () => void;
  onTriaged?: (updated: Finding) => void;
}) {
  return (
    <Drawer
      open={finding !== null}
      onClose={onClose}
      label={finding ? `Finding: ${finding.title}` : "Finding"}
    >
      {finding ? (
        <FindingDetail
          finding={finding}
          runId={runId}
          onTriaged={onTriaged}
          onClose={onClose}
        />
      ) : null}
    </Drawer>
  );
}
