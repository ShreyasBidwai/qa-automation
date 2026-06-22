import type { FormEvent } from "react";

import { Link } from "@/components/Link";
import { Button } from "@/components/ui/button";

import { AuthField, AuthLayout } from "./AuthLayout";

/** Forgot password — a static placeholder (no auth backend yet). Nothing submits. */
export function ForgotPasswordPage() {
  return (
    <AuthLayout
      title="Reset your password"
      subtitle="QA you can trust"
      footer={
        <Link to="/login" className="font-medium text-accent hover:underline">
          Back to sign in
        </Link>
      }
      note="Password reset isn't wired up yet — it lands in the next update."
    >
      <form
        className="space-y-4"
        onSubmit={(event: FormEvent) => event.preventDefault()}
      >
        <p className="text-sm text-muted-foreground">
          Enter your work email and we&rsquo;ll send a link to set a new password.
        </p>
        <AuthField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
        />
        <Button type="submit" className="w-full">
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  );
}
