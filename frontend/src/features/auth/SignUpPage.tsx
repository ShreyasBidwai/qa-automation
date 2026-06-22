import type { FormEvent } from "react";

import { Link } from "@/components/Link";
import { Button } from "@/components/ui/button";

import { AuthField, AuthLayout } from "./AuthLayout";

/** Sign up — a static placeholder (no auth backend yet). Nothing submits. */
export function SignUpPage() {
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
      <form
        className="space-y-4"
        onSubmit={(event: FormEvent) => event.preventDefault()}
      >
        <AuthField
          id="name"
          label="Name"
          autoComplete="name"
          placeholder="Ada Lovelace"
        />
        <AuthField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
        />
        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 12 characters"
        />
        <Button type="submit" className="w-full">
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
