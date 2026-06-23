import { useCallback, useEffect, useState } from "react";

import { orgApi } from "@/lib/api/client";
import type { InviteResponse, MemberResponse, OrgResponse } from "@/lib/api/types";

export interface TeamState {
  org: OrgResponse | null;
  members: MemberResponse[];
  pendingInvites: InviteResponse[];
  loading: boolean;
  error: string | null;
}

export interface TeamController extends TeamState {
  /** True when the caller's API-reported role can manage members (owner/admin). */
  canManage: boolean;
  /** True when the caller may manage owners (owner only) — the API still enforces. */
  canManageOwners: boolean;
  reload: () => void;
}

const EMPTY: TeamState = {
  org: null,
  members: [],
  pendingInvites: [],
  loading: true,
  error: null,
};

/**
 * Load the caller's team: the org they belong to (preferring a real team over the
 * personal org), its members, and — only when the caller can manage — the pending
 * invites. The caller's role comes from the API (OrgResponse.role) and gates the
 * UI; the API remains the authoritative security boundary.
 */
export function useTeam(): TeamController {
  const [state, setState] = useState<TeamState>(EMPTY);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState((current) => ({ ...current, loading: true, error: null }));

    void orgApi.listOrgs().then(async (orgsResult) => {
      if (cancelled) return;
      if (!orgsResult.ok || !orgsResult.data) {
        setState({
          ...EMPTY,
          loading: false,
          error: orgsResult.error ?? "Couldn't load your team.",
        });
        return;
      }
      const orgs = orgsResult.data.items;
      const org = orgs.find((candidate) => !candidate.is_personal) ?? orgs[0] ?? null;
      if (!org) {
        setState({ ...EMPTY, loading: false });
        return;
      }

      const canManage = org.role === "owner" || org.role === "admin";
      const [membersResult, invitesResult] = await Promise.all([
        orgApi.listMembers(org.id),
        canManage ? orgApi.listInvites(org.id) : Promise.resolve(null),
      ]);
      if (cancelled) return;
      if (!membersResult.ok || !membersResult.data) {
        setState({
          ...EMPTY,
          org,
          loading: false,
          error: membersResult.error ?? "Couldn't load members.",
        });
        return;
      }
      const pendingInvites =
        invitesResult && invitesResult.ok && invitesResult.data
          ? invitesResult.data.items.filter((invite) => invite.accepted_at === null)
          : [];
      setState({
        org,
        members: membersResult.data.items,
        pendingInvites,
        loading: false,
        error: null,
      });
    });

    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return {
    ...state,
    canManage: state.org?.role === "owner" || state.org?.role === "admin",
    canManageOwners: state.org?.role === "owner",
    reload,
  };
}
