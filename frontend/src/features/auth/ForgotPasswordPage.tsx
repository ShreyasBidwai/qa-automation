import { useState, type FormEvent } from "react";

import { Link } from "@/components/Link";

import { AuthField, AuthLayout, AuthSubmit } from "./AuthLayout";

/**
 * Reset password — presentation per Polaris Auth.dc.html. The reset flow isn't
 * wired yet (it lands in a later commit), so submitting says so honestly rather
 * than pretending to send a link.
 */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [note, setNote] = useState<string | null>(null);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setNote("Password reset isn’t available yet — it lands in a later update.");
  }

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your email and we’ll send a link to set a new password."
      footer={
        <>
          Remembered it?{" "}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Back to sign in
          </Link>
        </>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <AuthField
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />

        {note ? (
          <p role="status" className="text-sm text-muted-foreground">
            {note}
          </p>
        ) : null}

        <AuthSubmit>Send reset link</AuthSubmit>
      </form>
    </AuthLayout>
  );
}
