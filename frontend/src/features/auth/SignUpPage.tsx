import { useState, type FormEvent } from "react";

import { Link } from "@/components/Link";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/useAuth";

import { AuthField, AuthLayout } from "./AuthLayout";

const MIN_PASSWORD = 8;

/** Sign up — wired to the B2 session endpoint (name is set via the profile). */
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
      subtitle="QA you can trust"
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
        <AuthField
          id="name"
          label="Name"
          autoComplete="name"
          placeholder="Ada Lovelace"
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

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
