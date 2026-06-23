import { useState, type FormEvent } from "react";

import { Link } from "@/components/Link";
import type { FieldError } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/useAuth";

import { AuthField, AuthLayout, AuthSubmit } from "./AuthLayout";

/** Sign in — wired to the B2 session endpoint; presentation per Polaris Auth.dc.html. */
export function SignInPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>();
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setFieldErrors(undefined);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    const result = await signIn(email.trim(), password);
    // On success the auth context flips to authenticated and the app takes over;
    // only handle the failure path here.
    if (!result.ok) {
      setSubmitting(false);
      // B11: surface per-field validation messages where they belong; fall back
      // to a single message for credential / rate-limit (429) / generic errors.
      if (result.fieldErrors?.length) {
        setFieldErrors(result.fieldErrors);
      } else {
        setError(result.error ?? "Could not sign in. Try again.");
      }
    }
  }

  return (
    <AuthLayout
      title={
        <>
          Sign in to Polar<span className="text-accent">i</span>s
        </>
      }
      titleText="Sign in to Polaris"
      subtitle="Welcome back. Pick up where you left off."
      footer={
        <>
          New to Polaris?{" "}
          <Link to="/signup" className="font-medium text-accent hover:underline">
            Create account
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
          error={fieldErrors?.find((entry) => entry.field === "email")?.message}
        />
        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={fieldErrors?.find((entry) => entry.field === "password")?.message}
          labelAccessory={
            <Link
              to="/forgot"
              className="text-[12.5px] font-medium text-accent hover:underline"
            >
              Forgot password?
            </Link>
          }
        />

        {error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error}
          </p>
        ) : null}

        <AuthSubmit disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </AuthSubmit>
      </form>
    </AuthLayout>
  );
}
