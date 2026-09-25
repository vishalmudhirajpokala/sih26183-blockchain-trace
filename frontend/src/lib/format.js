/**
 * Shared vocabulary: how the UI names chains, statuses, risk and provenance.
 *
 * This file is where RULE 3/4/5 are won or lost in the browser. Every helper
 * here has the same contract: **a missing value renders as "Not available",
 * never as a plausible substitute.** There is deliberately no `?? 0`, no `?? "0"`,
 * and no `?? "unknown"` anywhere in it. A chain that could not be reached and
 * a chain that reported nothing are different facts and must not render
 * identically.
 *
 * Anything that needs to *mean* something — a chain name, a status sentence, a
 * provenance tier — has a mapping table keyed on the backend's own enum values.
 * An unrecognised key falls through to a neutral label, never to a guess about
 * which chain was meant.
 */

// ---------------------------------------------------------------------------
// CHAINS
// ---------------------------------------------------------------------------

/**
 * Chain display names, keyed on the exact `Chain` enum values in
 * `backend/models/schemas.py`. The key is the wire value, not a display
 * string, so a rename on the server shows up here as an unknown chain rather
 * than silently inheriting the old chain's label.
 */
const CHAIN_NAMES = {
  tron: "TRON",
  ethereum: "Ethereum",
  bsc: "BNB Smart Chain",
  polygon: "Polygon",
  bitcoin: "Bitcoin",
};

/** Every supported chain, in a stable display order. */
export const CHAIN_ORDER = ["tron", "ethereum", "bsc", "polygon", "bitcoin"];

/**
 * A short chain label for dense UI (badges, table cells).
 *
 * Falls back to the raw value when the chain is not one BlockTrace supports.
 * A new chain added on the server should still be *identifiable* in the UI
 * even before this table learns about it — showing the raw slug is honest,
 * guessing a pretty name is not.
 */
export function chainLabel(chain) {
  if (!chain) return "Not available";
  return CHAIN_NAMES[chain] ?? String(chain);
}

/** Abbreviated form, for table cells and axis labels. */
export function chainShort(chain) {
  if (!chain) return "N/A";
  return (
    { tron: "TRON", ethereum: "ETH", bsc: "BSC", polygon: "POLY", bitcoin: "BTC" }[chain] ??
    String(chain).toUpperCase()
  );
}

/** True when this chain is an EVM chain (the adapter distinguishes them). */
export function isEvmChain(chain) {
  return chain === "ethereum" || chain === "bsc" || chain === "polygon";
}

// ---------------------------------------------------------------------------
// TRACE STATUS
// ---------------------------------------------------------------------------

/**
 * How a trace ended, in the investigator's language.
 *
 * The distinction the backend makes between `no_match` (the provider answered
 * and has no history) and `provider_error` (the provider could not be reached)
 * is the single most important distinction in the product, so it is preserved
 * exactly. `tone` drives colour; `short` is the badge; `meaning` is the one-line
 * explanation an investigator needs in order to act.
 */
const STATUS = {
  matched: {
    short: "Matched",
    tone: "positive",
    meaning: "The trace reached a classified entity within the explored depth.",
  },
  no_match: {
    short: "No match",
    tone: "neutral",
    meaning:
      "The provider was reached and returned history, but no known entity was " +
      "found within the explored depth. This is a statement about the search, " +
      "not a clean bill of health.",
  },
  inconclusive: {
    short: "Inconclusive",
    tone: "neutral",
    meaning:
      "The trace ran but the evidence was too thin to support a conclusion. " +
      "Nothing was established either way.",
  },
  invalid_input: {
    short: "Invalid input",
    tone: "negative",
    meaning: "The input is not a valid address or transaction hash on any supported chain.",
  },
  provider_error: {
    short: "Provider error",
    tone: "negative",
    meaning:
      "The upstream data providers could not be reached. No conclusion about " +
      "this address can be drawn from this run.",
  },
  rate_limited: {
    short: "Rate limited",
    tone: "negative",
    meaning: "The providers rate-limited the request. The trace did not complete.",
  },
  timeout: {
    short: "Timed out",
    tone: "negative",
    meaning:
      "The investigation exceeded its time budget before the providers responded. " +
      "Narrowing the depth usually resolves this.",
  },
  partial: {
    /*
     * "Limited scope", not "Partial" and not a warning.
     *
     * This status means the trace stopped at a configured investigation
     * boundary -- usually the node ceiling on a busy address -- and is not a
     * failure. A run that explored 48 addresses and 66 transfers before
     * reaching the ceiling has produced a substantial, usable result, and
     * labelling it "PARTIAL" in large type made a good investigation read as a
     * broken one.
     *
     * The honesty is preserved rather than softened: `meaning` still says the
     * result covers only what was examined, and the exact boundary and the
     * addresses that hit it stay available under "Why limited?".
     */
    short: "Limited scope",
    tone: "caution",
    meaning:
      "The investigation stopped at its configured scope boundary, so the " +
      "results cover only the addresses actually examined. Activity may " +
      "continue beyond that boundary.",
  },
  depth_exceeded: {
    short: "Limited scope",
    tone: "caution",
    meaning:
      "The trace reached the configured depth limit, so the fund flow may " +
      "continue beyond it.",
  },
  unknown: {
    short: "Unknown",
    tone: "neutral",
    meaning: "The trace ended in a state the engine did not classify.",
  },
};

/** Status descriptor for a `TraceStatus` value, or a neutral fallback. */
export function statusInfo(status) {
  return (
    STATUS[status] ?? {
      short: status ? String(status) : "Not available",
      tone: "neutral",
      meaning: "The investigation ended in a state the engine did not classify.",
    }
  );
}

/**
 * True when a status means "we learned nothing because the data source
 * failed", as opposed to "we learned something and it was not what we hoped
 * for". The UI uses this to decide whether to show a retry prompt.
 */
export function isProviderFailure(status) {
  return ["provider_error", "rate_limited", "timeout"].includes(status);
}

// ---------------------------------------------------------------------------
// RISK
// ---------------------------------------------------------------------------

const RISK_TONE = {
  LOW: "positive",
  MEDIUM: "info",
  "MEDIUM-HIGH": "caution",
  HIGH: "caution-strong",
  CRITICAL: "negative",
  UNKNOWN: "neutral",
};

/** `positive | info | caution | caution-strong | negative | neutral` */
export function riskTone(level) {
  return RISK_TONE[level] ?? "neutral";
}

/** Tailwind classes for a risk badge, per level. */
export function riskBadgeClass(level) {
  const map = {
    positive: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
    info: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
    caution: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
    "caution-strong": "border-orange-300 bg-orange-50 text-orange-800 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300",
    negative: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
    neutral: "border-border bg-muted text-muted-foreground",
  };
  return map[RISK_TONE[level] ?? "neutral"] ?? map.neutral;
}

/** Human label for a `Severity` value. */
export function severityLabel(severity) {
  return (
    {
      info: "Info",
      low: "Low",
      medium: "Medium",
      high: "High",
      critical: "Critical",
    }[severity] ?? (severity ? String(severity) : "Not available")
  );
}

/** Tailwind classes for a severity chip. */
export function severityClass(severity) {
  const map = {
    info: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
    low: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
    medium: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
    high: "border-orange-300 bg-orange-50 text-orange-800 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300",
    critical: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  };
  return map[severity] ?? map.info;
}

// ---------------------------------------------------------------------------
// PROVENANCE  (RULE 4)
// ---------------------------------------------------------------------------

/**
 * What kind of claim an entity label is, and how much weight it carries.
 *
 * The wording is the point. `curated_verified` is a human decision with a
 * citation; `public_provider` is a label a provider attached; `heuristic` is a
 * pattern BlockTrace inferred. Presenting the third with the same confidence
 * as the first is how a forensic tool starts lying, so the tiers are rendered
 * in visibly different chrome and the note says which one is in play.
 */
const TIER = {
  curated_verified: {
    label: "Curated",
    title: "Entered by the investigation team and verified against a source",
    className:
      "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  },
  public_provider: {
    label: "Provider label",
    title: "A label the upstream data provider attached to this address",
    className:
      "border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200",
  },
  heuristic: {
    label: "Heuristic",
    title: "Inferred by BlockTrace from transaction patterns, not from a named source",
    className:
      "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
  },
  none: {
    label: "No attribution",
    title: "No entity label is associated with this address",
    className: "border-border bg-muted text-muted-foreground",
  },
};

export function provenanceTier(tier) {
  return (
    TIER[tier] ?? {
      label: "Unclassified",
      title: "This attribution does not match any provenance tier the engine records.",
      className: "border-border bg-muted text-muted-foreground",
    }
  );
}

const VERIFICATION = {
  verified: "Verified",
  unverified: "Unverified",
  disputed: "Disputed",
};

export function verificationLabel(status) {
  return VERIFICATION[status] ?? (status ? String(status) : "Not available");
}

// ---------------------------------------------------------------------------
// ENTITY TYPES
// ---------------------------------------------------------------------------

const ENTITY_TYPE = {
  exchange: "Exchange",
  mixer: "Mixer",
  sanctioned: "Sanctioned",
  high_risk: "High risk",
  service: "Service",
  unknown: "Unclassified",
};

export function entityTypeLabel(type) {
  return ENTITY_TYPE[type] ?? (type ? String(type) : "Not available");
}

export function entityTypeClass(type) {
  const map = {
    exchange: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
    mixer: "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-300",
    sanctioned: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
    high_risk: "border-orange-300 bg-orange-50 text-orange-800 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300",
    service: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
    unknown: "border-border bg-muted text-muted-foreground",
  };
  return map[type] ?? map.unknown;
}

// ---------------------------------------------------------------------------
// VALUES
// ---------------------------------------------------------------------------

/** The literal rendered wherever a value is genuinely not available. */
export const NOT_AVAILABLE = "Not available";

/**
 * Render any possibly-absent value, or say plainly that it is absent.
 *
 * `0`, `""` and `false` are *values* and render as themselves — only `null`,
 * `undefined` and the empty string become "Not available". Getting this backwards
 * is how a real zero balance gets rendered as "no data".
 */
export function value(v, fallback = NOT_AVAILABLE) {
  if (v === null || v === undefined || v === "") return fallback;
  if (typeof v === "number" && !Number.isFinite(v)) return fallback;
  return v;
}

/**
 * Format a token amount.
 *
 * `decimals` comes from the provider; when it is absent the amount is shown at
 * full precision rather than being divided by a guessed 18. A wrong scale is a
 * fabricated number, and a fabricated number is worse than an ugly one.
 */
export function formatAmount(amount, decimals, asset) {
  if (amount === null || amount === undefined || !Number.isFinite(Number(amount))) {
    return NOT_AVAILABLE;
  }
  const numeric = Number(amount);
  const suffix = asset ? ` ${asset}` : "";

  if (decimals === null || decimals === undefined) {
    // The provider gave a value with no scale. Show it as-is and mark the unit
    // as unknown rather than assuming the chain's conventional decimals.
    return `${numeric.toLocaleString()}${suffix}`;
  }

  const places = Number(decimals);
  if (!Number.isInteger(places) || places < 0 || places > 30) {
    return `${numeric.toLocaleString()}${suffix}`;
  }
  return `${numeric.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: Math.min(places, 8),
  })}${suffix}`;
}

/**
 * A unix timestamp (seconds) as a local date-time string.
 *
 * Block timestamps are in seconds; anything carrying `> 1e12` is milliseconds.
 * The unit is *checked*, not assumed, because reading milliseconds as seconds
 * produces a date in the year 56000 that looks like real data.
 */
export function formatTimestamp(ts) {
  if (ts === null || ts === undefined || !Number.isFinite(Number(ts))) {
    return NOT_AVAILABLE;
  }
  const raw = Number(ts);
  if (raw <= 0) return NOT_AVAILABLE;
  const ms = raw > 1e12 ? raw : raw * 1000;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return NOT_AVAILABLE;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** An ISO-8601 string (or unix seconds) as `YYYY-MM-DD HH:MM:SS` UTC. */
export function formatDateTime(iso) {
  if (!iso) return NOT_AVAILABLE;
  // Bare numbers are unix seconds (the engine's `started_at`); strings are ISO.
  if (typeof iso === "number" || /^\d{9,13}$/.test(String(iso))) {
    return formatTimestamp(iso);
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return NOT_AVAILABLE;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** `1,234` for a count that exists; "Not available" when it does not. */
export function formatCount(n) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) {
    return NOT_AVAILABLE;
  }
  return Number(n).toLocaleString();
}

/** `1.2 s` / `340 ms` for a measured duration. */
export function formatDuration(ms) {
  if (ms === null || ms === undefined || !Number.isFinite(Number(ms))) {
    return NOT_AVAILABLE;
  }
  const n = Number(ms);
  if (n < 1000) return `${Math.round(n)} ms`;
  if (n < 60000) return `${(n / 1000).toFixed(1)} s`;
  return `${Math.floor(n / 60000)}m ${Math.round((n % 60000) / 1000)}s`;
}

/** A unix timestamp as a coarse relative age, for "x minutes ago" lists. */
export function formatRelative(iso) {
  if (!iso) return NOT_AVAILABLE;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return NOT_AVAILABLE;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 2592000) return `${Math.floor(seconds / 86400)}d ago`;
  return formatDateTime(iso);
}

/**
 * Truncate a hash or address for display, keeping it recognisable.
 *
 * The full value is always available to copy and is never replaced — only the
 * *rendered* string is shortened. A truncated address that cannot be told apart
 * from its neighbours is not evidence.
 */
export function truncateHash(valueToTruncate, lead = 8, tail = 6) {
  if (!valueToTruncate) return NOT_AVAILABLE;
  const text = String(valueToTruncate);
  if (text.length <= lead + tail + 1) return text;
  return `${text.slice(0, lead)}…${text.slice(-tail)}`;
}

// ---------------------------------------------------------------------------
// AVS EXPLORER LINKS
// ---------------------------------------------------------------------------

/**
 * A public block-explorer URL for an address or hash.
 *
 * These are constructed from the chain, not looked up: they are navigation
 * aids, and the explorer itself is the authority, not this string. The pattern
 * per chain is a documented property of the public explorer, not a claim about
 * chain data. The app never claims to have *read* the explorer.
 */
const EXPLORERS = {
  tron: "https://tronscan.org/#",
  ethereum: "https://etherscan.io",
  bsc: "https://bscscan.com",
  polygon: "https://polygonscan.com",
  bitcoin: "https://mempool.space",
};

/** Path segments per chain for an address, then a hash. */
const EXPLORER_PATHS = {
  tron: { address: "address", hash: "transaction" },
  ethereum: { address: "address", hash: "tx" },
  bsc: { address: "address", hash: "tx" },
  polygon: { address: "address", hash: "tx" },
  bitcoin: { address: "address", hash: "tx" },
};

export function explorerUrl(chain, kind, target) {
  if (!chain || !target) return null;
  const base = EXPLORERS[chain];
  const path = EXPLORER_PATHS[chain]?.[kind];
  if (!base || !path) return null;
  return `${base}/${path}/${encodeURIComponent(target)}`;
}

/**
 * A provider-supplied URL, reduced to something safe to put in an `href`.
 *
 * `source_url` on an attribution comes from whichever public provider or
 * curated list produced the label, which means it is attacker-influenceable
 * input: anyone who can get a name attached to an address may control the URL
 * shown beside it. React escapes the attribute, so a quote cannot break out —
 * but `href` is not an attribute in that sense. It is a URL, and `href`
 * accepts any scheme, so a `javascript:` value executes on click inside this
 * origin, where the session token is readable from localStorage. The
 * `target="_blank"` and `rel="noopener noreferrer"` that sit next to these
 * links do not prevent that; they only stop the opened page from reaching
 * back through `window.opener`.
 *
 * So the scheme is checked rather than assumed. Returning `null` is a normal
 * outcome and not an error: a provenance row with an unusable URL still shows
 * its name, address, and source label — it just loses the link, which is the
 * correct thing to lose.
 */
export function safeSourceUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  let parsed;
  try {
    // No base, so a relative URL fails to parse and is rejected. A source
    // citation is an external reference; a bare path is not one.
    parsed = new URL(value.trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
  return parsed.href;
}
