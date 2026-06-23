import { createContext, useContext } from "react";

import type { ApiResult } from "@/lib/api/client";
import type { AuthTokenResponse, AuthUser } from "@/lib/api/types";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  signIn: (email: string, password: string) => Promise<ApiResult<AuthTokenResponse>>;
  signUp: (
    email: string,
    password: string,
    name?: string,
  ) => Promise<ApiResult<AuthTokenResponse>>;
  signOut: () => Promise<void>;
  /** Replace the cached user (e.g. after a profile update) so chrome stays in sync. */
  setUser: (user: AuthUser) => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

/** Access the auth session. Throws if used outside the AuthProvider. */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return value;
}
