import type { FormEvent } from "react";

import { Link } from "@/components/Link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { AuthField, AuthLayout } from "./AuthLayout";

/** Sign in — a static placeholder (no auth backend yet). Nothing submits. */
export function SignInPage() {
  return (
    <AuthLayout
      title="Sign in"
      subtitle="QA you can trust"
      footer={
        <>
          New to Polaris?{" "}
          <Link to="/signup" className="font-medium text-accent hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(event: FormEvent) => event.preventDefault()}
      >
        <AuthField
          id="email"
          label="Work email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
        />
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="password" className="text-sm font-medium text-foreground">
              Password
            </label>
            <Link
              to="/forgot"
              className="text-xs font-medium text-accent hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••"
          />
        </div>
        <Button type="submit" className="w-full">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
