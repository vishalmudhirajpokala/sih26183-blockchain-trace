/**
 * Shared presentational pieces.
 *
 * The important ones here are `NotAvailable`, `EmptyState`, `ErrorPanel` and
 * `ValueRow`, because they are the components that *do not lie*. Every
 * investigation surface in the app is assembled from them, so the rule that a
 * missing value says so is enforced in one place rather than restated in nine
 * pages and forgotten in the tenth.
 */

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  Info,
  Loader2,
  Minus,
  RefreshCw,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  NOT_AVAILABLE,
  chainLabel,
  explorerUrl,
  formatDateTime,
  provenanceTier,
  riskBadgeClass,
  riskTone,
  severityClass,
  severityLabel,
  truncateHash,
  value,
} from "@/lib/format";

// ---------------------------------------------------------------------------
// ABSENCE
// ---------------------------------------------------------------------------

/**
 * The explicit marker for a value that does not exist.
 *
 * This is a component rather than a string so it is visually consistent and so
 * it can be found by search. An em-dash in a table cell could be a value, a
 * truncation, or a rendering bug; this says which.
 */
export function NotAvailable({ reason, className = "" }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-muted-foreground ${className}`}
      title={reason}
    >
      <Minus className="size-3" aria-hidden="true" />
      <span className="not-italic">{NOT_AVAILABLE}</span>
    </span>
  );
}

/** A labelled value that renders `Not available` rather than a blank cell. */
export function Value({ children, reason, className = "" }) {
  const missing = children === null || children === undefined || children === "" || children === NOT_AVAILABLE;
  if (missing) return <NotAvailable reason={reason} className={className} />;
  return <span className={className}>{children}</span>;
}

/** A `label: value` row for evidence panels. `value` may be anything. */
export function ValueRow({ label, children, mono = false, reason, copyable = false }) {
  const raw = typeof children === "string" ? children : null;
  return (
    <div className="grid gap-1 py-2 sm:grid-cols-[minmax(9rem,14rem)_1fr] sm:items-baseline sm:gap-4">
      <span className="text-xs font-medium tracking-wide text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-start gap-2">
        <span
          className={`min-w-0 break-all text-sm ${mono || raw ? "font-mono text-xs" : ""}`}
        >
          <Value reason={reason}>{children}</Value>
        </span>
        {copyable && raw ? <CopyButton value={raw} /> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EMPTY / ERROR / LOADING
// ---------------------------------------------------------------------------

/**
 * "There is nothing here" — and, where it matters, *why*.
 *
 * An empty list with no explanation is indistinguishable from a broken query.
 * Every caller passes what was actually asked for, so the reader can tell
 * "no cases yet" from "the filter matched nothing" from "the backend could not
 * be reached".
 */
export function EmptyState({
  icon: Icon = Info,
  title,
  description,
  action = null,
  tone = "neutral",
}) {
  const toneClass =
    tone === "negative"
      ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40"
      : tone === "caution"
        ? "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40"
        : "border-dashed";
  const iconClass =
    tone === "negative"
      ? "text-red-600 dark:text-red-400"
      : tone === "caution"
        ? "text-amber-600 dark:text-amber-400"
        : "text-muted-foreground";

  return (
    <div className={`flex flex-col items-center rounded-xl border px-6 py-12 text-center ${toneClass}`}>
      <Icon className={`size-6 ${iconClass}`} aria-hidden="true" />
      <h3 className="mt-3 text-sm font-semibold">{title}</h3>
      {description ? (
        <p className="mt-1.5 max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/**
 * A failure, rendered with its *kind* intact.
 *
 * The API returns `{error, detail, kind}` and this keeps `kind` visible, because
 * the kind decides the response: a provider-side failure invites a retry, an
 * input error invites a correction, and a not-found invites a look at the id.
 * Collapsing them into "something went wrong" is the failure mode this whole
 * project is about.
 */
export function ErrorPanel({ error, onRetry = null, className = "" }) {
  if (!error) return null;

  const kind = error.kind || "internal";
  const providerSide =
    ["provider_error", "rate_limited", "timeout", "unavailable"].includes(kind);
  const notFound = kind === "not_found";
  const input = kind === "invalid_input";

  const heading = notFound
    ? "Not found"
    : providerSide
      ? "A data provider could not be reached"
      : input
        ? "That input was rejected"
        : "The request failed";

  const Icon = providerSide ? AlertTriangle : Info;

  return (
    <div
      className={`flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950/40 ${className}`}
      role="alert"
    >
      <Icon className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-red-800 dark:text-red-200">{heading}</p>
        <p className="mt-1 leading-6 text-red-700 dark:text-red-300">
          {/* `message` is what `ApiError` carries, but callers that hand-build
              an error object from a raw API payload use `detail`. Both are
              accepted here rather than showing an empty red box, which is what
              happened when a caller passed only `detail`. */}
          {error.message ||
            error.detail ||
            "The request failed and the reason was not reported."}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-red-200 bg-white text-red-700 dark:border-red-900 dark:bg-transparent dark:text-red-300">
            {kind}
          </Badge>
          {error.status ? (
            <span className="text-xs text-red-600 dark:text-red-400">HTTP {error.status}</span>
          ) : null}
        </div>
        {providerSide ? (
          <p className="mt-2 text-xs leading-5 text-red-600 dark:text-red-400">
            This says the upstream data source was unavailable. It is not a finding about the
            address you traced.
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="shrink-0 self-start">
          <RefreshCw className="mr-1.5 size-3.5" />
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/** A loading row that matches the shape of a table, so the page does not jump. */
export function TableSkeleton({ rows = 5, cols = 4 }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-6 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** An inline spinner with a stated reason, for a section that is still working. */
export function LoadingBlock({ label = "Loading" }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SMALL WIDGETS
// ---------------------------------------------------------------------------

/** Copy-to-clipboard with visible confirmation, and an honest failure path. */
export function CopyButton({ value: text, label = "Copy", size = "sm" }) {
  const [state, setState] = useState("idle");

  useEffect(() => {
    if (state !== "copied") return undefined;
    const timer = setTimeout(() => setState("idle"), 1400);
    return () => clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard?.writeText(text);
      setState("copied");
    } catch {
      // A clipboard the browser refuses is a real failure, so it is shown as
      // one rather than silently pretending the value was copied.
      setState("failed");
      setTimeout(() => setState("idle"), 1600);
    }
  }

  return (
    <Button
      type="button"
      variant="outline"
      size={size}
      onClick={copy}
      className="h-6 shrink-0 px-1.5 text-xs"
      title={state === "failed" ? "The browser blocked clipboard access" : label}
    >
      {state === "copied" ? (
        <Check className="size-3" aria-hidden="true" />
      ) : (
        <Copy className="size-3" aria-hidden="true" />
      )}
      <span className="sr-only">{label}</span>
    </Button>
  );
}

/** A monospace address/hash with a copy button, truncated for display. */
export function AddressChip({ value: text, chain, href = true, lead = 8, tail = 6 }) {
  if (!text) return <NotAvailable />;
  const url = href ? explorerUrl(chain, "address", text) : null;
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5">
      <code className="truncate font-mono text-xs" title={text}>
        {truncateHash(text, lead, tail)}
      </code>
      <CopyButton value={text} />
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer noopener"
          className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
          title={`Open in the ${chainLabel(chain)} block explorer`}
        >
          <ExternalLink className="size-3" aria-hidden="true" />
          <span className="sr-only">Open in block explorer</span>
        </a>
      ) : null}
    </span>
  );
}

/** A transaction hash chip, linked to the explorer when the chain is known. */
export function HashChip({ value: text, chain, lead = 10, tail = 8 }) {
  if (!text) return <NotAvailable />;
  const url = explorerUrl(chain, "hash", text);
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5">
      <code className="truncate font-mono text-xs" title={text}>
        {truncateHash(text, lead, tail)}
      </code>
      <CopyButton value={text} />
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer noopener"
          className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
          title={`Open in the ${chainLabel(chain)} block explorer`}
        >
          <ExternalLink className="size-3" aria-hidden="true" />
          <span className="sr-only">Open in block explorer</span>
        </a>
      ) : null}
    </span>
  );
}

/** A risk level as a badge, using the shared tone scale. */
export function RiskBadge({ level, score = null, className = "" }) {
  return (
    <Badge variant="outline" className={`${riskBadgeClass(level)} ${className}`}>
      {level ?? "UNKNOWN"}
      {typeof score === "number" ? (
        <span className="font-mono opacity-70">{score}</span>
      ) : null}
    </Badge>
  );
}

/** A provenance chip. The title explains what the tier is worth (RULE 4). */
export function ProvenanceChip({ tier, className = "" }) {
  const info = provenanceTier(tier);
  return (
    <Badge variant="outline" title={info.title} className={`${info.className} ${className}`}>
      {info.label}
    </Badge>
  );
}

/** A risk-indicator severity chip. */
export function SeverityChip({ severity, children }) {
  return (
    <Badge variant="outline" className={severityClass(severity)}>
      {children ?? severityLabel(severity)}
    </Badge>
  );
}

/**
 * A labelled statistic.
 *
 * `hint` is shown under the value, and it is never merged into the number
 * itself: a hint that qualified the figure would render as part of the figure
 * on a screenshot, and a screenshot of a chart is exactly where a
 * qualification is most likely to be lost.
 */
export function StatCard({
  label,
  value: statValue,
  hint = null,
  icon: Icon = null,
  tone = null,
}) {
  const missing = statValue === null || statValue === undefined || statValue === NOT_AVAILABLE;
  const toneClass =
    tone === "negative"
      ? "text-red-600 dark:text-red-400"
      : tone === "caution"
        ? "text-amber-600 dark:text-amber-400"
        : tone === "positive"
          ? "text-emerald-600 dark:text-emerald-400"
          : "";
  const riskClass = tone ? riskBadgeClass(riskTone(tone)) : "";

  return (
    <Card size="sm">
      <CardContent className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <p className={`mt-1.5 text-2xl font-semibold tracking-tight ${missing ? "text-muted-foreground" : toneClass}`}>
            {missing ? <span className="text-base font-normal">Not available</span> : statValue}
          </p>
          {hint ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{hint}</p> : null}
        </div>
        {Icon ? (
          <div className={`flex size-8 shrink-0 items-center justify-center rounded-md border bg-muted/40 ${riskClass}`}>
            <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** A horizontal bar for a 0–100 quantity, with the scale stated. */
export function ScoreBar({ score, max = 100, label = null, tone = null }) {
  if (typeof score !== "number" || !Number.isFinite(score)) {
    return <NotAvailable reason="No score was reported for this investigation." />;
  }
  const pct = Math.max(0, Math.min(100, (score / max) * 100));
  const barTone =
    tone === "negative"
      ? "bg-red-500"
      : tone === "caution"
        ? "bg-amber-500"
        : tone === "positive"
          ? "bg-emerald-500"
          : "bg-primary";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{label ?? `0–${max}`}</span>
        <span className="font-mono font-semibold">{score}</span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${barTone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/**
 * The evidence ledger.
 *
 * The engine returns `evidence_notes[]`: sentences written by the provider
 * layer explaining what was and was not established. They are rendered verbatim
 * and never summarised, because a paraphrase of an evidence note is no longer
 * evidence — it is a claim about evidence.
 */
export function EvidenceNotes({ notes, title = "Evidence notes", className = "" }) {
  if (!Array.isArray(notes) || notes.length === 0) return null;
  /*
   * Report-renderer notes are dropped from the web UI entirely.
   *
   * The orchestrator records a note when the PDF fails, and that note arrives as
   * data: "The PDF dossier could not be rendered (ValueError)." On the web page
   * it was noise about the document generator sitting inside the investigation
   * view -- an exception class name, in a panel about blockchain evidence, on a
   * case whose transactions and risk are perfectly fine. The report is an export
   * of the investigation, not part of it.
   *
   * The note is not deleted: it stays in the stored result and in the exported
   * PDF, which is the right place for a renderer diagnostic. Here it is simply
   * not about the investigation, so it is not shown.
   */
  const shown = notes.filter((note) => !REPORT_RENDERER_NOTE.test(String(note)));
  if (shown.length === 0) return null;
  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <Info className="size-3.5 text-muted-foreground" aria-hidden="true" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
      </div>
      <ul className="mt-2 space-y-2">
        {shown.map((note, i) => (
          <li
            key={i}
            className="rounded-md border border-dashed bg-muted/30 px-3 py-2 text-xs leading-5 text-muted-foreground"
          >
            {humaniseNote(note)}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Matches a stored note about the PDF/report renderer failing. */
const REPORT_RENDERER_NOTE = /(?:pdf|dossier|report)[^.]*could not be (?:rendered|generated|created)/i;

/**
 * Strip a Python exception class name out of a stored note.
 *
 * Anything else the orchestrator recorded with the exception type interpolated
 * in, e.g. "...failed (TimeoutError)", is rewritten to say what happened without
 * naming the internal type. The type is accurate and it is useful to whoever
 * debugs, but it is a name in the implementation, not a finding about the case.
 * Nothing is invented and no note is dropped: a note with no exception class in
 * it passes through untouched.
 */
const EXCEPTION_IN_PARENS = /\s*\(([A-Z][A-Za-z0-9_]*(?:Error|Exception))\)/g;

function humaniseNote(note) {
  if (typeof note !== "string") return note;
  // A fresh non-global regex for the guard: `EXCEPTION_IN_PARENS` is global, and
  // testing a global regex advances its `lastIndex`, so the check would skip
  // every other note in a list.
  if (!new RegExp(EXCEPTION_IN_PARENS.source).test(note)) return note;
  const cleaned = note
    .replace(EXCEPTION_IN_PARENS, "")
    .replace(/\s+\./g, ".")
    .replace(/\s{2,}/g, " ")
    .trim();
  // A note that was nothing but an exception name has no user-safe wording to
  // fall back on, so it is kept rather than silently blanked.
  return cleaned || note;
}

/**
 * Which providers actually served this investigation, and how they went.
 *
 * This is the audit trail for RULE 5. A trace that succeeded after one provider
 * failed should show both facts, not only the success.
 */
export function ProviderLedger({ usage, className = "" }) {
  if (!Array.isArray(usage) || usage.length === 0) return null;
  return (
    <div className={className}>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Provider activity
      </h3>
      <ul className="mt-2 space-y-1.5">
        {usage.map((p, i) => (
          <li
            key={`${p.provider}-${i}`}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-card px-3 py-2 text-xs"
          >
            <span
              className={`size-1.5 shrink-0 rounded-full ${p.ok ? "bg-emerald-500" : "bg-red-500"}`}
              aria-hidden="true"
            />
            <span className="font-medium">{p.provider || "Unnamed provider"}</span>
            <span className={p.ok ? "text-muted-foreground" : "text-red-600 dark:text-red-400"}>
              {p.ok ? "responded" : "failed"}
            </span>
            {p.status_code ? (
              <span className="text-muted-foreground">HTTP {p.status_code}</span>
            ) : null}
            {typeof p.latency_ms === "number" ? (
              <span className="text-muted-foreground">{p.latency_ms} ms</span>
            ) : null}
            {p.retries ? (
              <span className="text-muted-foreground">{p.retries} retries</span>
            ) : null}
            {p.error ? <span className="text-red-600 dark:text-red-400">{p.error}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A collapsible section.
 *
 * A real `<button>` with `aria-expanded` and `aria-controls`, not a styled
 * `<div>`: these sections carry methodology, provider attribution and scope
 * limits, so they have to be reachable and announceable by keyboard and screen
 * reader rather than merely look clickable.
 *
 * Native `<details>` was the previous mechanism on this page. It is replaced here
 * because it cannot be given a chevron, an id for `aria-controls`, or a
 * consistent row height, and because `summary` inside a flex row needs
 * `list-none`/`marker:hidden` patching that is easy to get wrong per browser.
 */
export function Disclosure({
  label,
  hint = null,
  children,
  defaultOpen = false,
  className = "",
  bodyClassName = "",
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [bodyId] = useState(() => `disclosure-${Math.random().toString(36).slice(2, 9)}`);

  return (
    <div className={`rounded-xl border bg-card/50 ${className}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <ChevronRight
          className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden="true"
        />
        <span>{label}</span>
        {hint ? (
          <span className="truncate text-xs font-normal text-muted-foreground">
            {hint}
          </span>
        ) : null}
      </button>
      {open ? (
        <div id={bodyId} className={`border-t px-4 py-3 ${bodyClassName}`}>
          {children}
        </div>
      ) : null}
    </div>
  );
}

/** A page header with a title, an explanatory line, and an action slot. */
export function PageHeader({ eyebrow = null, title, description = null, actions = null }) {
  return (
    <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0 space-y-1.5">
        {eyebrow ? (
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-primary">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

/** A section card with a title, an optional right-hand control, and a body. */
export function SectionCard({ title, description = null, action = null, children, className = "", bodyClassName = "" }) {
  return (
    <Card className={className}>
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-sm">{title}</CardTitle>
            {description ? <CardDescription className="mt-1">{description}</CardDescription> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </div>
      </CardHeader>
      <CardContent className={bodyClassName}>{children}</CardContent>
    </Card>
  );
}

/** Horizontal key/value statistics grid used across the result pages. */
export function StatGrid({ items, className = "" }) {
  return (
    <dl className={`grid grid-cols-2 divide-x divide-y md:grid-cols-4 md:divide-y-0 ${className}`}>
      {items.map((item) => (
        <div key={item.label} className="p-4">
          <dt className="text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {item.tooltip ? (
              <span title={item.tooltip}>
                {item.value}
              </span>
            ) : (
              item.value
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * A read-only provider textarea styled as a field.
 *
 * Used for copy-pasteable raw values (an address, a hash) where the full string
 * matters more than its appearance.
 */
export function MonoField({ children, onCopy = null }) {
  const ref = useRef(null);
  return (
    <div className="flex items-start gap-2 rounded-md border bg-muted/30 px-3 py-2">
      <code ref={ref} className="min-w-0 flex-1 break-all font-mono text-xs">
        {children}
      </code>
      {onCopy ? <CopyButton value={onCopy} /> : null}
    </div>
  );
}

export { Separator, value, formatDateTime };
