import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({
  authApi: {
    me: vi.fn(),
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    updateProfile: vi.fn(),
  },
}));

import { authApi } from "@/lib/api/client";

import { AuthProvider } from "./AuthContext";
import { clearToken, getToken, setToken } from "./session";
import { useAuth } from "./useAuth";

function Probe() {
  const { status, user, signIn, signOut } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="email">{user?.email ?? "—"}</span>
      <button type="button" onClick={() => void signIn("a@b.com", "pw123456")}>
        do-signin
      </button>
      <button type="button" onClick={() => void signOut()}>
        do-signout
      </button>
    </div>
  );
}

const SESSION = {
  ok: true as const,
  status: 200,
  data: {
    access_token: "tok-1",
    token_type: "bearer",
    user: { id: "u1", email: "a@b.com", name: null, created_at: "2026-01-01" },
  },
};

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    clearToken();
    vi.clearAllMocks();
  });

  it("is anonymous with no persisted token (and never calls /me)", async () => {
    renderProbe();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    expect(authApi.me).not.toHaveBeenCalled();
  });

  it("authenticates and persists the token on sign-in", async () => {
    vi.mocked(authApi.signIn).mockResolvedValue(SESSION);
    renderProbe();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );

    fireEvent.click(screen.getByText("do-signin"));

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
    expect(screen.getByTestId("email")).toHaveTextContent("a@b.com");
    expect(getToken()).toBe("tok-1");
  });

  it("validates a persisted token via /me on load", async () => {
    setToken("persisted");
    vi.mocked(authApi.me).mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "u1", email: "me@b.com", name: null, created_at: "2026-01-01" },
    });

    renderProbe();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
    expect(authApi.me).toHaveBeenCalled();
    expect(screen.getByTestId("email")).toHaveTextContent("me@b.com");
  });

  it("drops a rejected persisted token and falls back to anonymous", async () => {
    setToken("stale");
    vi.mocked(authApi.me).mockResolvedValue({
      ok: false,
      status: 401,
      data: null,
      error: "authentication required",
    });

    renderProbe();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    expect(getToken()).toBeNull();
  });

  it("clears the session on sign-out", async () => {
    vi.mocked(authApi.signIn).mockResolvedValue(SESSION);
    vi.mocked(authApi.signOut).mockResolvedValue({ ok: true, status: 204, data: null });
    renderProbe();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );

    fireEvent.click(screen.getByText("do-signin"));
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );

    fireEvent.click(screen.getByText("do-signout"));
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    expect(getToken()).toBeNull();
  });
});
