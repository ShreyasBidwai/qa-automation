import {
  AlertTriangle,
  ChevronRight,
  CreditCard,
  MoreHorizontal,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authApi, orgApi } from "@/lib/api/client";
import type {
  FieldError,
  InviteResponse,
  MemberResponse,
  OrgRoleName,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";
import { cn } from "@/lib/utils";

import { useTeam } from "./useTeam";

const ROLES: OrgRoleName[] = ["owner", "admin", "member", "viewer"];

function roleLabel(role: OrgRoleName): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

// Role pill colours (Polaris Account.dc.html): owner indigo, admin/member quiet.
function roleViz(role: OrgRoleName): { text: string; bg: string } {
  if (role === "owner") return { text: "text-accent", bg: "bg-accent-subtle" };
  if (role === "admin")
    return { text: "text-foreground-secondary", bg: "bg-status-neutral-bg" };
  return { text: "text-muted-foreground", bg: "bg-background" };
}

function initials(name: string | null | undefined, email: string): string {
  const source = (name ?? "").trim() || email;
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  const letters = (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "");
  return letters.toUpperCase() || email.slice(0, 2).toUpperCase();
}

function fieldError(
  errors: FieldError[] | undefined,
  name: string,
): string | undefined {
  return errors?.find((entry) => entry.field === name)?.message;
}

type Tab = "profile" | "team";

/** Account & Team (Polaris Account.dc.html) — wired to B2/B3. */
export function AccountPage() {
  const [tab, setTab] = useState<Tab>("profile");

  return (
    <PageShell
      scroll={false}
      maxWidth="max-w-[960px]"
      header={
        <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
          Account
        </h1>
      }
    >
      {/* Header + tab bar stay put (ADR-0066); only the active panel scrolls. */}
      <div role="tablist" className="mb-7 flex shrink-0 gap-1 border-b border-border">
        <TabButton
          id="profile"
          active={tab === "profile"}
          onClick={() => setTab("profile")}
        >
          Profile
        </TabButton>
        <TabButton id="team" active={tab === "team"} onClick={() => setTab("team")}>
          Team
        </TabButton>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "profile" ? (
          <div role="tabpanel" aria-labelledby="tab-profile">
            <ProfileTab />
          </div>
        ) : (
          <div role="tabpanel" aria-labelledby="tab-team">
            <TeamTab />
          </div>
        )}
      </div>
    </PageShell>
  );
}

function TabButton({
  id,
  active,
  onClick,
  children,
}: {
  id: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      id={`tab-${id}`}
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "-mb-px border-b-2 px-3.5 py-2.5 text-[13.5px] font-medium transition-colors",
        active
          ? "border-accent text-foreground"
          : "border-transparent text-status-neutral-solid hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

// ---- profile ----------------------------------------------------------------

function ProfileTab() {
  const { user } = useAuth();
  return (
    <div>
      <div className="mb-7 flex items-center gap-4">
        <Avatar
          label={initials(user?.name, user?.email ?? "")}
          className="h-14 w-14 bg-accent text-[20px] text-accent-foreground"
        />
        <div className="min-w-0">
          <div className="text-base font-semibold text-foreground">
            {user?.name?.trim() || "Your account"}
          </div>
          <div className="mt-0.5 truncate font-mono text-[12.5px] text-muted-foreground">
            {user?.email}
          </div>
        </div>
      </div>

      <ProfileForm />
      <ChangePasswordForm />
      <BillingLink />
    </div>
  );
}

/** A quiet doorway from the account into the customer pricing page (B5) — billing lives
 *  in the account context, kept off the main workflow nav. */
function BillingLink() {
  return (
    <Link
      to="/pricing"
      className="mt-4 flex items-center gap-3.5 rounded-xl border border-border bg-surface p-5 shadow-card transition-colors hover:bg-background"
    >
      <span className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border-[1.5px] border-marker">
        <CreditCard className="h-4 w-4 text-status-neutral-solid" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-foreground">
          Plans &amp; pricing
        </span>
        <span className="mt-0.5 block text-[12.5px] text-muted-foreground">
          Compare what each Polaris plan includes — seats, run credits, and quotas.
        </span>
      </span>
      <ChevronRight
        className="h-4 w-4 flex-none text-status-neutral-solid"
        aria-hidden="true"
      />
    </Link>
  );
}

function ProfileForm() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FieldError[] | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setErrors(undefined);
    setSaved(false);
    setSaving(true);
    const result = await authApi.updateProfile({
      name: name.trim() ? name.trim() : null,
      email: email.trim() || undefined,
    });
    setSaving(false);
    if (result.ok && result.data) {
      setUser(result.data);
      setSaved(true);
      return;
    }
    setErrors(result.fieldErrors);
    if (!result.fieldErrors?.length) {
      setError(result.error ?? "Couldn't save your profile.");
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card>
        <Field
          id="name"
          label="Name"
          value={name}
          onChange={setName}
          placeholder="Jordan Lee"
          autoComplete="name"
          error={fieldError(errors, "name")}
        />
        <Field
          id="email"
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          mono
          error={fieldError(errors, "email")}
        />
        {error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error}
          </p>
        ) : null}
        {saved ? (
          <p role="status" className="text-sm text-status-pass-fg">
            Changes saved.
          </p>
        ) : null}
      </Card>
      <div className="mb-5 mt-4 flex justify-end">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}

function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FieldError[] | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setErrors(undefined);
    setConfirmError(null);
    setDone(false);
    if (next !== confirm) {
      setConfirmError("Passwords don't match.");
      return;
    }
    setSaving(true);
    const result = await authApi.changePassword({
      current_password: current,
      new_password: next,
    });
    setSaving(false);
    if (result.ok) {
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
      return;
    }
    setErrors(result.fieldErrors);
    if (!result.fieldErrors?.length) {
      setError(result.error ?? "Couldn't change your password.");
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <Card>
        <h2 className="text-sm font-semibold text-foreground">Change password</h2>
        <Field
          id="current_password"
          label="Current password"
          type="password"
          value={current}
          onChange={setCurrent}
          placeholder="••••••••"
          autoComplete="current-password"
          error={fieldError(errors, "current_password")}
        />
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <Field
            id="new_password"
            label="New password"
            type="password"
            value={next}
            onChange={setNext}
            placeholder="At least 8 characters"
            autoComplete="new-password"
            error={fieldError(errors, "new_password")}
          />
          <Field
            id="confirm_password"
            label="Confirm"
            type="password"
            value={confirm}
            onChange={setConfirm}
            placeholder="Re-enter"
            autoComplete="new-password"
            error={confirmError ?? undefined}
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error}
          </p>
        ) : null}
        {done ? (
          <p role="status" className="text-sm text-status-pass-fg">
            Password changed.
          </p>
        ) : null}
        <div className="flex justify-end">
          <Button type="submit" variant="outline" disabled={saving}>
            {saving ? "Updating…" : "Update password"}
          </Button>
        </div>
      </Card>
    </form>
  );
}

// ---- team -------------------------------------------------------------------

function TeamTab() {
  const team = useTeam();

  if (team.loading) {
    return <Skeleton className="h-72 rounded-xl" />;
  }
  if (team.error) {
    return (
      <StatePanel
        icon={AlertTriangle}
        tone="danger"
        title="Couldn't load your team"
        description="Polaris couldn't reach the team service. This is usually temporary."
        code={team.error}
      />
    );
  }
  if (!team.org) {
    return (
      <StatePanel
        icon={Users}
        title="No team yet"
        description="You're not part of a team org yet. Create or join one to manage members here."
      />
    );
  }

  const peopleCount = team.members.length + team.pendingInvites.length;

  return (
    <div>
      {team.canManage ? (
        <InviteForm
          orgId={team.org.id}
          canInviteOwner={team.canManageOwners}
          onInvited={team.reload}
        />
      ) : null}

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Members</h2>
        <span className="text-xs text-status-neutral-solid">
          {peopleCount} {peopleCount === 1 ? "person" : "people"}
        </span>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
        {team.members.map((member) => (
          <MemberRow
            key={member.user_id}
            orgId={team.org!.id}
            member={member}
            canManage={team.canManage}
            canManageOwners={team.canManageOwners}
            onChanged={team.reload}
          />
        ))}
        {team.pendingInvites.map((invite) => (
          <PendingRow key={invite.id} invite={invite} />
        ))}
      </div>
    </div>
  );
}

function InviteForm({
  orgId,
  canInviteOwner,
  onInvited,
}: {
  orgId: string;
  canInviteOwner: boolean;
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRoleName>("member");
  const [sending, setSending] = useState(false);
  const [errors, setErrors] = useState<FieldError[] | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const assignable = ROLES.filter((value) => canInviteOwner || value !== "owner");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setErrors(undefined);
    setSent(null);
    setSending(true);
    const result = await orgApi.invite(orgId, { email: email.trim(), role });
    setSending(false);
    if (result.ok && result.data) {
      setSent(result.data.email);
      setEmail("");
      onInvited();
      return;
    }
    setErrors(result.fieldErrors);
    if (!result.fieldErrors?.length) {
      setError(result.error ?? "Couldn't send the invite.");
    }
  }

  const emailError = fieldError(errors, "email");

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="mb-5 rounded-xl border border-border bg-surface p-5 shadow-card"
    >
      <div className="mb-3 text-[13px] font-semibold text-foreground">
        Invite a member
      </div>
      <div className="flex flex-col gap-2.5 sm:flex-row">
        <div className="flex-1">
          <Label htmlFor="invite-email" className="sr-only">
            Email to invite
          </Label>
          <Input
            id="invite-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@company.com"
            autoComplete="off"
            aria-invalid={emailError ? true : undefined}
            aria-describedby={emailError ? "invite-email-error" : undefined}
            className="font-mono text-[13px]"
          />
        </div>
        <div>
          <Label htmlFor="invite-role" className="sr-only">
            Invite role
          </Label>
          <select
            id="invite-role"
            value={role}
            onChange={(event) => setRole(event.target.value as OrgRoleName)}
            className="h-9 rounded-lg border border-border bg-background px-3 text-sm font-medium text-foreground-secondary transition-colors focus-visible:border-accent"
          >
            {assignable.map((value) => (
              <option key={value} value={value}>
                {roleLabel(value)}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={sending} className="whitespace-nowrap">
          {sending ? "Sending…" : "Send invite"}
        </Button>
      </div>
      {emailError ? (
        <p id="invite-email-error" className="mt-2 text-xs text-status-fail-fg">
          {emailError}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-xs text-status-fail-fg">
          {error}
        </p>
      ) : null}
      {sent ? (
        <p role="status" className="mt-2 text-xs text-status-pass-fg">
          Invite sent to {sent}.
        </p>
      ) : null}
    </form>
  );
}

function MemberRow({
  orgId,
  member,
  canManage,
  canManageOwners,
  onChanged,
}: {
  orgId: string;
  member: MemberResponse;
  canManage: boolean;
  canManageOwners: boolean;
  onChanged: () => void;
}) {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isSelf = user?.id === member.user_id;
  // The API is authoritative; the client only hides what it knows will be refused:
  // managers may act on others, but an admin may not manage an owner.
  const manageable =
    canManage && !isSelf && (canManageOwners || member.role !== "owner");

  async function changeRole(role: OrgRoleName) {
    setError(null);
    setBusy(true);
    const result = await orgApi.changeRole(orgId, member.user_id, { role });
    setBusy(false);
    if (result.ok) onChanged();
    else setError(result.error ?? "Couldn't change the role.");
  }

  async function remove() {
    setError(null);
    setBusy(true);
    const result = await orgApi.removeMember(orgId, member.user_id);
    setBusy(false);
    if (result.ok) onChanged();
    else setError(result.error ?? "Couldn't remove the member.");
  }

  const viz = roleViz(member.role);

  return (
    <div className="border-b border-border-subtle last:border-b-0">
      <div className="flex items-center gap-3.5 px-[18px] py-3.5">
        <Avatar
          label={initials(member.name, member.email)}
          className={cn(
            "h-[34px] w-[34px] text-xs",
            member.role === "owner"
              ? "bg-accent text-accent-foreground"
              : "bg-status-neutral-bg text-status-neutral-fg",
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground">
            {member.name?.trim() || member.email}
            {isSelf ? (
              <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                (you)
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 truncate font-mono text-[11.5px] text-status-neutral-solid">
            {member.email}
          </div>
        </div>
        <RolePill role={member.role} viz={viz} />
        {manageable ? (
          <MemberMenu
            name={member.name?.trim() || member.email}
            currentRole={member.role}
            canAssignOwner={canManageOwners}
            busy={busy}
            onChangeRole={changeRole}
            onRemove={remove}
          />
        ) : (
          <span className="w-5" aria-hidden="true" />
        )}
      </div>
      {error ? (
        <p role="alert" className="px-[18px] pb-3 text-xs text-status-fail-fg">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function PendingRow({ invite }: { invite: InviteResponse }) {
  const viz = roleViz(invite.role);
  return (
    <div className="flex items-center gap-3.5 border-b border-border-subtle px-[18px] py-3.5 last:border-b-0">
      <Avatar
        label={initials(null, invite.email)}
        className="h-[34px] w-[34px] bg-background text-xs text-status-neutral-solid"
      />
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[13px] text-foreground">
          {invite.email}
        </div>
      </div>
      <Badge level="flaky">Invite pending</Badge>
      <RolePill role={invite.role} viz={viz} />
      <span className="w-5" aria-hidden="true" />
    </div>
  );
}

function RolePill({
  role,
  viz,
}: {
  role: OrgRoleName;
  viz: { text: string; bg: string };
}) {
  return (
    <span
      className={cn(
        "min-w-[64px] rounded-md px-2.5 py-[3px] text-center text-xs font-medium",
        viz.bg,
        viz.text,
      )}
    >
      {roleLabel(role)}
    </span>
  );
}

function MemberMenu({
  name,
  currentRole,
  canAssignOwner,
  busy,
  onChangeRole,
  onRemove,
}: {
  name: string;
  currentRole: OrgRoleName;
  canAssignOwner: boolean;
  busy: boolean;
  onChangeRole: (role: OrgRoleName) => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const assignable = ROLES.filter(
    (role) => role !== currentRole && (canAssignOwner || role !== "owner"),
  );

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Manage ${name}`}
        disabled={busy}
        onClick={() => setOpen((value) => !value)}
        className="flex h-7 w-5 items-center justify-center rounded text-status-neutral-solid transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-8 z-10 w-44 overflow-hidden rounded-lg border border-border bg-surface py-1 shadow-card"
        >
          {assignable.map((role) => (
            <button
              key={role}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onChangeRole(role);
              }}
              className="block w-full px-3 py-1.5 text-left text-[13px] text-foreground-secondary hover:bg-background"
            >
              Make {roleLabel(role)}
            </button>
          ))}
          <div className="my-1 border-t border-border-subtle" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onRemove();
            }}
            className="block w-full px-3 py-1.5 text-left text-[13px] text-status-fail-fg hover:bg-status-fail-bg"
          >
            Remove from team
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ---- shared bits ------------------------------------------------------------

function Card({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-4 rounded-xl border border-border bg-surface p-6 shadow-card">
      {children}
    </div>
  );
}

function Avatar({ label, className }: { label: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex flex-none items-center justify-center rounded-full font-semibold",
        className,
      )}
    >
      {label}
    </span>
  );
}

function Field({
  id,
  label,
  type,
  value,
  onChange,
  placeholder,
  autoComplete,
  error,
  mono,
}: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
  error?: string;
  mono?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={mono ? "font-mono text-[13px]" : undefined}
      />
      {error ? (
        <p id={`${id}-error`} className="text-xs text-status-fail-fg">
          {error}
        </p>
      ) : null}
    </div>
  );
}
