/**
 * The one place the frontend talks to the investigation API.
 *
 * Three rules govern this file.
 *
 * 1. **No credentials live here except the user's own session token.** There is
 *    no API key, no Supabase service-role key, and no provider key in browser
 *    code — not even a placeholder that could be filled in and committed. Every
 *    privileged credential stays in the backend process.
 *
 * 2. **Errors keep their structure.** The API returns `{error, detail, kind}`;
 *    a caller that needs to distinguish "your input was wrong" from "the
 *    provider is down" gets that distinction. Anything that flattens it to
 *    `Error(string)` destroys the only signal that separates those cases, so
 *    this returns a typed `ApiError` instead.
 *
 * 3. **Nothing is defaulted into existence.** A missing field arrives as
 *    `undefined` and the UI renders "not available". It is never backfilled
 *    with a plausible value.
 */

const RAW_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export const API_BASE = String(RAW_BASE).replace(/\/+$/, "");

// ---------------------------------------------------------------------------
// SESSION
// ---------------------------------------------------------------------------

const TOKEN_KEY = "blocktrace.session";

/**
 * The signed-in user's session, or null.
 *
 * A session token is the only credential the browser holds. It is scoped to
 * this origin's own cases and carries no provider or database privilege.
 * `expires_at` is kept so the UI can warn *before* a request fails, rather
 * than after.
 */
export function readSession() {
  try {
    const raw = window.localStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.access_token) return null;
    return parsed;
  } catch {
    // A corrupt entry is treated as no session rather than crashing the app on
    // every load. The user simply signs in again.
    return null;
  }
}

export function writeSession(session) {
  try {
    window.localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
  } catch {
    /* Private-browsing quota failures must not break tracing. */
  }
}

export function clearSession() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to do */
  }
}

function authHeader() {
  const session = readSession();
  return session?.access_token
    ? { Authorization: `Bearer ${session.access_token}` }
    : {};
}

// ---------------------------------------------------------------------------
// ERRORS
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor({ error, detail, kind, status, detection }) {
    super(detail || error || "The request failed.");
    this.name = "ApiError";
    this.error = error || "request_failed";
    this.kind = kind || "internal";
    this.status = status ?? 0;
    this.detection = detection || null;
  }

  /**
   * True when the failure is about *availability*, not about the user's input.
   * The UI says these differently: one invites a retry, the other invites a
   * correction.
   */
  get isProviderSide() {
    return ["provider_error", "rate_limited", "timeout", "unavailable"].includes(
      this.kind,
    );
  }
}

async function request(path, { method = "GET", body, signal, timeout = 120000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  // Let a caller-supplied signal (an in-flight request being superseded) and
  // our own timeout both reach the same controller.
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...authHeader(),
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (response.status === 204) return null;

    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = null;
      }
    }

    if (!response.ok) {
      // FastAPI puts a structured error object in `detail`. A legacy handler
      // may put a bare string there instead, so both shapes are read.
      const detail = payload?.detail ?? payload;
      if (detail && typeof detail === "object") {
        throw new ApiError({
          error: detail.error,
          detail: detail.detail,
          kind: detail.kind,
          detection: detail.detection,
          status: response.status,
        });
      }
      throw new ApiError({
        error: "request_failed",
        detail: typeof detail === "string" ? detail : `Request failed (${response.status}).`,
        kind: response.status === 404 ? "not_found" : "internal",
        status: response.status,
      });
    }

    return payload;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err?.name === "AbortError") {
      throw new ApiError({
        error: "aborted",
        detail: "The request was cancelled or timed out before it completed.",
        kind: "timeout",
      });
    }
    throw new ApiError({
      error: "network_unreachable",
      detail:
        "Could not reach the BlockTrace API. Check that the backend is running " +
        "and that VITE_API_URL points at it.",
      kind: "unavailable",
    });
  } finally {
    clearTimeout(timer);
  }
}

function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

// ---------------------------------------------------------------------------
// ENDPOINTS
// ---------------------------------------------------------------------------

export const api = {
  health: () => request("/health", { timeout: 15000 }),

  authStatus: () => request("/auth/status", { timeout: 15000 }),

  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password }, timeout: 20000 }),

  signUp: (email, password) =>
    request("/auth/signup", { method: "POST", body: { email, password }, timeout: 20000 }),

  logout: () => request("/auth/logout", { method: "POST", timeout: 15000 }),

  /**
   * Identify an input. Cheap — no provider call — so the console calls it
   * debounced while the user types.
   */
  detect: (queryText, preferredChain, signal) =>
    request("/trace/detect", {
      method: "POST",
      body: { query: queryText, preferred_chain: preferredChain || null },
      signal,
      timeout: 20000,
    }),

  chains: () => request("/network/chains", { timeout: 15000 }),

  runTrace: (body, signal) =>
    request("/trace/run", { method: "POST", body, signal, timeout: 300000 }),

  investigations: (params) => request(`/investigations${query(params)}`, { timeout: 30000 }),

  investigation: (id) => request(`/investigations/${encodeURIComponent(id)}`, { timeout: 30000 }),

  deleteInvestigation: (id) =>
    request(`/investigations/${encodeURIComponent(id)}`, { method: "DELETE", timeout: 20000 }),

  analyticsOverview: () => request("/analytics/overview", { timeout: 30000 }),

  riskTrend: () => request("/analytics/risk-trend", { timeout: 30000 }),

  entities: (params) => request(`/entities${query(params)}`, { timeout: 30000 }),

  entityTypes: () => request("/entities/types", { timeout: 30000 }),

  entityDetail: (chain, address) =>
    request(`/entities/${encodeURIComponent(chain)}/${encodeURIComponent(address)}`, {
      timeout: 30000,
    }),

  reports: (params) => request(`/reports${query(params)}`, { timeout: 30000 }),

  regenerateReport: (investigationId) =>
    request(`/reports/${encodeURIComponent(investigationId)}/regenerate`, {
      method: "POST",
      timeout: 120000,
    }),

  networkOverview: () => request("/network/overview", { timeout: 90000 }),
};

/**
 * A report URL the backend returned, as an absolute URL.
 *
 * The API returns a path. A path is not openable from a different origin, so it
 * is resolved against the API base rather than left to the browser to guess.
 *
 * An absolute URL is accepted only when it points back at the configured API
 * origin. The old test here was `/^https?:\/\//`, which checked the scheme and
 * nothing else: any host the backend happened to name would become the
 * destination of a button labelled "Download PDF". Comparing origins is the
 * check that matches the intent — this is *our* report store, or it is not a
 * report. A deployment that legitimately moves reports to object storage sets
 * `VITE_API_URL` to the same origin, or widens this to an explicit host
 * allowlist.
 */
export function reportHref(reportPath) {
  if (!reportPath) return null;
  if (/^https?:\/\//i.test(reportPath)) {
    try {
      const candidate = new URL(reportPath);
      const ours = new URL(API_BASE);
      return candidate.origin === ours.origin ? candidate.href : null;
    } catch {
      return null;
    }
  }
  const name = String(reportPath).replace(/\\/g, "/").split("/").pop();
  if (!name) return null;
  return `${API_BASE}/reports/${encodeURIComponent(name)}`;
}
