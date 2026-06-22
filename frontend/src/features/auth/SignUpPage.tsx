import { useState, type FormEvent } from "react";

import { Link } from "@/components/Link";
import { useAuth } from "@/lib/auth/useAuth";

import {
  AuthDivider,
  AuthField,
  AuthLayout,
  AuthSubmit,
  SsoButton,
} from "./AuthLayout";

const MIN_PASSWORD = 8;

/** Sign up — wired to B2; presentation per Polaris Auth.dc.html. */
export function SignUpPage() {
  const { signUp } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError("Enter your work email.");
      return;
    }
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for your password.`);
      return;
    }
    setSubmitting(true);
    const result = await signUp(email.trim(), password, name);
    if (!result.ok) {
      setSubmitting(false);
      setError(result.error ?? "Could not create your account. Try again.");
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start finding problems before your users do."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <SsoButton label="Sign up with SSO" />
        <AuthDivider />
        <AuthField
          id="name"
          label="Name"
          autoComplete="name"
          placeholder="Jordan Lee"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <AuthField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 8 characters"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        {error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error}
          </p>
        ) : null}

        <AuthSubmit disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </AuthSubmit>
      </form>
    </AuthLayout>
  );
}
