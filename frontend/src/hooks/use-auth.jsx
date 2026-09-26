/**
 * Authentication state, mirroring `backend/services/auth.py`.
 *
 * Three states, kept deliberately distinct — the browser must not collapse
 * them any more than the server does:
 *
 *   AUTHENTICATED  a real user session the backend has verified
 *   ANONYMOUS      demo mode: reachable, nothing private, no account
 *   UNAVAILABLE    this deployment requires sign-in and no session is present
 *
 * `UNAVAILABLE` is not "not signed in, so hide everything". It is "this
 * deployment is locked", and the correct response is to send the operator to
 * the sign-in page rather than to render an empty dashboard that looks like
 * "you have no cases".
 *
 * The only credential in this file is the user's own session token. There is no
 * Supabase key, anon or service-role, anywhere in the browser.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, clearSession, readSession, writeSession } from "@/lib/api";
import {
  clearOAuthCallback as clearGoogleCallback,
  readOAuthCallback as readGoogleCallback,
  signInWithGoogle as googleSignIn,
} from "@/lib/supabase";

const ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000";
const ANONYMOUS_EMAIL = "demo@blocktrace.local";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSessionState] = useState(() => readSession());
  // `null` status means the capability endpoint has not answered yet. The UI
  // shows a loading state rather than guessing a mode.
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const setSession = useCallback((next) => {
    if (next) writeSession(next);
    else clearSession();
    setSessionState(next);
  }, []);

  const refreshStatus = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.authStatus();
      // A deployment with no Supabase cannot verify a token. Holding one would
      // be pointless and misleading, so it is dropped rather than kept.
      if (next?.mode === "locked" && !next?.supabase_configured) {
        clearSession();
        setSessionState(null);
      }
      setStatus(next);
      return next;
    } catch {
      // A failed capability check is itself information. `status` stays null
      // and `loading` ends, so pages render their unreachable state rather
      // than an indefinite spinner.
      setStatus(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const login = useCallback(
    async (email, password) => {
      const result = await api.login(email, password);
      setSession({
        access_token: result.access_token,
        refresh_token: result.refresh_token,
        expires_at: result.expires_at,
        user: result.user,
      });
      await refreshStatus();
      return result;
    },
    [setSession, refreshStatus],
  );

  const signUp = useCallback(
    async (email, password) => {
      // `POST /auth/signup` deliberately returns no token: it answers with
      // `{user_id, email, session, confirmation_required}` where `session` is a
      // *boolean*, not a session object. There is nothing to store here even
      // when registration succeeded, so this never writes a session. The caller
      // signs in separately, which is why a successful sign-up cannot silently
      // look like a successful sign-in.
      const result = await api.signUp(email, password);
      await refreshStatus();
      return result;
    },
    [refreshStatus],
  );

  /**
   * Sign in with Google through Supabase's OAuth handshake.
   *
   * Supabase returns a Supabase access token, which is the same credential the
   * backend already verifies, so the session that lands here is
   * indistinguishable from one produced by the email/password path. No new
   * backend verification route was needed for that reason.
   */
  const signInWithGoogle = useCallback(async () => {
    const result = await googleSignIn();
    if (result.ok) {
      // A full navigation, not a client-side push: the Google consent screen
      // and the return trip are outside React's control.
      window.location.assign(result.redirectTo);
      return { ok: true };
    }
    return result;
  }, []);

  /**
   * Collect a session Google just delivered, once, on mount.
   *
   * The tokens arrive in the URL hash. They are read, stored through the same
   * path an email/password login uses, and then removed from the address bar so
   * a refresh or a shared link does not replay them. Replay is harmless --
   * they are the user's own tokens -- but a token sitting in a URL is a token
   * in browser history, in a referrer header and in a screenshot.
   */
  const ingestOAuthCallback = useCallback(async () => {
    const tokens = await readGoogleCallback();
    if (!tokens) return null;
    clearGoogleCallback();
    setSession({ ...tokens, provider: "google" });
    await refreshStatus();
    return tokens;
  }, [setSession, refreshStatus]);

  /*
   * Ingest a Google session on the way back from the consent screen.
   *
   * Mount-time rather than login-page-time on purpose: Supabase can deliver
   * the callback to any URL in the redirect allowlist, and a user who follows
   * a bookmark straight to /app should still end up signed in rather than
   * looking at a route guard with a token in the address bar it never used.
   *
   * Declared below `ingestOAuthCallback` for a real reason, not style: a
   * dependency array is evaluated during render, so an effect listed above the
   * `const` that defines its own callback reads it in its temporal dead zone.
   */
  useEffect(() => {
    ingestOAuthCallback();
  }, [ingestOAuthCallback]);

  const logout = useCallback(async () => {
    try {
      const current = readSession();
      if (current?.access_token) await api.logout();
    } catch {
      // A failed revocation does not make the local token usable to anyone
      // else once it is discarded here, and the discard is the part the user
      // asked for. The failure is swallowed deliberately.
    } finally {
      clearSession();
      setSessionState(null);
      await refreshStatus();
    }
  }, [refreshStatus]);

  /**
   * Who the operator is, or null.
   *
   * In demo mode there is a real identity on the server side — the namespaced
   * anonymous id — and it is surfaced rather than hidden, so a saved case in a
   * demo is visibly a demo case.
   */
  const user = useMemo(() => {
    const id = session?.user?.id;
    if (id) {
      const email = session.user.email || null;
      return {
        id,
        email,
        name: email ? String(email).split("@")[0] : "Investigator",
        isDemo: false,
      };
    }
    if (status?.demo_mode) {
      return { id: ANONYMOUS_USER_ID, email: ANONYMOUS_EMAIL, name: "Demo investigator", isDemo: true };
    }
    return null;
  }, [session, status]);

  /**
   * Whether the app may read case data.
   *
   * `isDemo` counts as access, because a demo deployment is deliberately
   * open. What it does *not* do is imply the data is private.
   */
  const canAccess = Boolean(status && (status.mode === "live" || status.mode === "demo"));

  const value = useMemo(
    () => ({
      session,
      status,
      loading,
      user,
      isAuthenticated: status?.mode === "live" && Boolean(session?.access_token),
      isDemo: Boolean(status?.demo_mode),
      isLocked: status?.mode === "locked",
      canAccess,
      login,
      signUp,
      signInWithGoogle,
      ingestOAuthCallback,
      logout,
      refreshStatus,
      setSession,
    }),
    [
      session,
      status,
      loading,
      user,
      canAccess,
      login,
      signUp,
      signInWithGoogle,
      ingestOAuthCallback,
      logout,
      refreshStatus,
      setSession,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside an <AuthProvider>");
  return context;
}
