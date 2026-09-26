/**
 * The Supabase browser client, used for OAuth sign-in only.
 *
 * WHY THIS IS SEPARATE FROM `api.js`
 * ---------------------------------
 * `api.js` talks to the BlockTrace backend. This talks to Supabase, and only
 * for the OAuth handshake. The two are kept apart so that the Supabase anon
 * key is never sent to BlockTrace, and so a missing Supabase configuration
 * cannot break the API client that every page depends on.
 *
 * WHY SUPABASE RATHER THAN GOOGLE DIRECTLY
 * ----------------------------------------
 * Supabase's `signInWithOAuth` returns a *Supabase* access token, and the
 * backend already verifies exactly that: `services/auth.resolve_identity` hands
 * the bearer token to Supabase's `auth.get_user`. So Google sign-in arrives as
 * an ordinary Supabase session and needs no new verification path, no new
 * callback route, and no Google client secret anywhere in this repository.
 * That is the whole reason for choosing it over raw Google Identity.
 *
 * The Google client secret stays in the Supabase dashboard. There is no secret
 * in this codebase to leak, which matters for a system that will hold case data.
 *
 * WHEN IT IS ABSENT
 * -----------------
 * `getSupabase()` returns null rather than throwing. Every caller must handle
 * that: a deployment with no Supabase is in demo mode, it works, and a missing
 * auth provider must never take the application down. This mirrors how every
 * blockchain provider in `adapters/` degrades to "unavailable" rather than
 * failing a trace.
 */

import { createClient } from "@supabase/supabase-js";

// Read from the same VITE_ convention `api.js` uses, so one .env file
// configures the whole frontend.
const URL = import.meta.env.VITE_SUPABASE_URL || "";
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || "";

/** True when this deployment has enough configuration to attempt a sign-in. */
export const isSupabaseConfigured = Boolean(URL && ANON_KEY);

let client = null;

/**
 * The Supabase client, or null when unconfigured.
 *
 * Built lazily and cached, so an unconfigured deployment never pays for the
 * import and never has a half-built client floating around.
 */
export function getSupabase() {
  if (!isSupabaseConfigured) return null;
  if (!client) {
    client = createClient(URL, ANON_KEY, {
      auth: {
        // Supabase otherwise parks a session in localStorage under its own key.
        // BlockTrace's session lives through `use-auth`, which is what every
        // page reads, so a second copy would be a second source of truth that
        // can disagree with the first.
        persistSession: false,
        autoRefreshToken: false,
        detectSessionInUrl: false,
      },
    });
  }
  return client;
}

/**
 * The URL Google should return the user to.
 *
 * The origin only, deliberately. `useLocation` is not consulted because a
 * redirect target built from the current path could send a returning user to
 * whichever page they happened to be on, including a deep link into somebody
 * else's case.
 */
export function oauthRedirectTo() {
  return `${window.location.origin}/login`;
}

/**
 * Start a Google sign-in.
 *
 * Returns a discriminated result rather than throwing, because the two failure
 * modes mean different things to a user and the UI must say which happened:
 *
 *   { ok: false, reason: "not_configured" }  this deployment has no Supabase
 *   { ok: false, reason: "cancelled" }       the user closed the Google popup
 *   { ok: false, reason: "error", detail }   anything else
 */
export async function signInWithGoogle() {
  const supabase = getSupabase();
  if (!supabase) return { ok: false, reason: "not_configured" };

  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: oauthRedirectTo() },
  });

  if (error) {
    // Supabase reports a user-closed popup as an error, and it is not one.
    if (/cancel|closed|denied/i.test(error.message || "")) {
      return { ok: false, reason: "cancelled" };
    }
    return { ok: false, reason: "error", detail: error.message || "Sign-in failed." };
  }

  // `data.url` is the Google consent URL. The browser must actually navigate
  // to it; there is no popup to open, because the redirect carries the session
  // back through the address bar and a popup would be a second navigation to
  // keep in sync.
  return { ok: true, redirectTo: data?.url || oauthRedirectTo() };
}

/**
 * Read a session out of the URL after Google returns.
 *
 * Supabase's implicit flow puts the tokens in the hash fragment:
 * `#access_token=...&refresh_token=...`. `detectSessionInUrl` is off, so this
 * does that job explicitly and hands the tokens back in the same shape
 * `use-auth` already stores for an email/password session.
 *
 * Returns null when there is nothing to collect, which is the normal case on a
 * first visit.
 */
export async function readOAuthCallback() {
  const supabase = getSupabase();
  if (!supabase) return null;

  const hash = window.location.hash || "";
  if (!hash.includes("access_token=")) return null;

  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const accessToken = params.get("access_token");
  if (!accessToken) return null;

  const { data, error } = await supabase.auth.getSession();
  if (error || !data?.session) {
    // Fall back to what the URL carried, so a transient network failure does
    // not silently drop a user who has just authenticated.
    return {
      access_token: accessToken,
      refresh_token: params.get("refresh_token") || null,
    };
  }

  return {
    access_token: data.session.access_token,
    refresh_token: data.session.refresh_token || null,
  };
}

/** Strip the tokens from the address bar once they have been collected. */
export function clearOAuthCallback() {
  if (window.location.hash) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
  }
}
