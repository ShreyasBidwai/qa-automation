import { useEffect, useState, type ReactNode } from "react";

import { authApi } from "@/lib/api/client";
import type { AuthUser } from "@/lib/api/types";

import { clearToken, getToken, setToken, subscribeToken } from "./session";
import { AuthContext, type AuthStatus } from "./useAuth";

/**
 * Holds the signed-in user and the session lifecycle (B2). On mount it validates
 * a persisted token via GET /auth/me; sign-in / sign-up establish + persist a
 * token; a 401 anywhere clears it (the client drops the token, we hear it via the
 * session subscription) and the app falls back to sign-in.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  // Validate a persisted token once on load.
  useEffect(() => {
    let cancelled = false;
    if (!getToken()) {
      setStatus("anonymous");
      return;
    }
    void authApi.me().then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setUser(result.data);
        setStatus("authenticated");
      } else {
        clearToken();
        setUser(null);
        setStatus("anonymous");
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // If the token is dropped elsewhere (a 401 from any data call), sign out.
  useEffect(
    () =>
      subscribeToken(() => {
        if (!getToken()) {
          setUser(null);
          setStatus("anonymous");
        }
      }),
    [],
  );

  async function signIn(email: string, password: string) {
    const result = await authApi.signIn({ email, password });
    if (result.ok && result.data) {
      setToken(result.data.access_token);
      setUser(result.data.user);
      setStatus("authenticated");
    }
    return result;
  }

  async function signUp(email: string, password: string, name?: string) {
    const result = await authApi.signUp({ email, password });
    if (result.ok && result.data) {
      setToken(result.data.access_token);
      let nextUser = result.data.user;
      // Sign-up takes only email + password; persist the display name (if given)
      // with a best-effort profile update — failure doesn't block the session.
      if (name && name.trim()) {
        const updated = await authApi.updateProfile({ name: name.trim() });
        if (updated.ok && updated.data) nextUser = updated.data;
      }
      setUser(nextUser);
      setStatus("authenticated");
    }
    return result;
  }

  async function signOut() {
    await authApi.signOut();
    clearToken();
    setUser(null);
    setStatus("anonymous");
  }

  return (
    <AuthContext.Provider value={{ status, user, signIn, signUp, signOut, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}
