/**
 * Network explorer — live chain status, per chain.
 *
 * RULE 5 in its purest form. A network panel wants every cell filled, and the
 * two easiest ways to lie here are to render `0` for a metric that was never
 * measured and to render a cached tip as a live one. So:
 *
 *  - An absent metric renders "Not available" with the reason. Never a zero.
 *  - A chain whose providers are unreachable renders its failure as a failure.
 *    An unreachable provider is not a chain at height zero.
 *  - TPS is never derived from block height, because block time alone cannot
 *    tell you how full a block is. The backend marks it `not_provided` and this
 *    page says so.
 *  - Average block time is labelled as a documented protocol parameter, not a
 *    measurement taken during this request.
 *
 * The page loads on mount and on explicit refresh only. There is no background
 * polling, because a value that silently changes under the reader is a value
 * with no timestamp the reader can check.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { api } from "@/lib/api";
import { formatCount, formatDateTime, formatTimestamp } from "@/lib/format";
import {
  Disclosure,
  ErrorPanel,
  LoadingBlock,
  PageHeader,
  SectionCard,
  ValueRow,
} from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** `tps_availability` values the backend emits, and what each one means. */
const TPS_NOTE = {
  not_provided:
    "No provider this deployment uses exposes transactions-per-second. It is reported as not provided rather than estimated from block height, because block time alone cannot tell you how full a block is.",
  unavailable:
    "The provider could not be reached, so this figure is unknown rather than zero.",
};

function AvailabilityBadge({ available }) {
  return (
    <Badge variant={available ? "secondary" : "outline"}>
      {available ? "Reachable" : "Not reachable"}
    </Badge>
  );
}

/**
 * One chain. `null` is passed through to NotAvailable rather than being
 * coerced, so an unmeasured metric is visibly unmeasured.
 */
function MetricRow({ label, value, reason, mono = true, unit = null }) {
  return (
    <ValueRow
      label={label}
      mono={mono}
      reason={value === null || value === undefined ? reason : null}
    >
      {value === null || value === undefined ? null : `${formatCount(value)}${unit ? ` ${unit}` : ""}`}
    </ValueRow>
  );
}

function ChainCard({ entry }) {
  const available = Boolean(entry?.available);
  const tpsProvided = entry?.tps_availability === "available";
  const tps = tpsProvided ? entry?.tps : null;

  return (
    <SectionCard
      title={entry?.chain_name || entry?.chain || "Unknown chain"}
      description={available ? null : entry?.unavailable_reason}
      action={<AvailabilityBadge available={available} />}
    >
      <dl className="divide-y">
        <MetricRow
          label="Block height"
          value={available ? entry?.block_height : null}
          reason={
            available
              ? "The provider responded but did not report a block height. It is shown as not available rather than as 0, which would be a different and false statement."
              : entry?.unavailable_reason ||
                "The provider could not be reached, so no block height is known."
          }
        />

        <ValueRow
          label="Block timestamp"
          mono={false}
          reason={
            available && !entry?.block_timestamp
              ? "The provider did not report a block timestamp."
              : !available
                ? "No live data, so no timestamp."
                : null
          }
        >
          {available && entry?.block_timestamp
            ? formatTimestamp(entry.block_timestamp)
            : null}
        </ValueRow>

        <ValueRow
          label="Transactions"
          reason={
            available && entry?.transaction_count === null
              ? "Not reported by this provider."
              : !available
                ? "No live data."
                : null
          }
        >
          {available && typeof entry?.transaction_count === "number"
            ? formatCount(entry.transaction_count)
            : null}
        </ValueRow>

        <ValueRow
          label="Transactions / second"
          reason={
            !available
              ? "The provider could not be reached, so this figure is unknown rather than zero."
              : TPS_NOTE[entry?.tps_availability] ||
                "This provider does not report transactions-per-second."
          }
        >
          {tps !== null ? formatCount(tps) : null}
        </ValueRow>

        <ValueRow
          label="Average block time"
          reason={
            !entry?.average_block_time_seconds
              ? "No block-time parameter is recorded for this chain."
              : null
          }
        >
          {entry?.average_block_time_seconds
            ? `${entry.average_block_time_seconds}s`
            : null}
        </ValueRow>

        {entry?.block_time_source ? (
          <ValueRow label="Block time source" mono={false}>
            {entry.block_time_source}
          </ValueRow>
        ) : null}
      </dl>

      {/*
        Which provider served this, and when it was asked, is audit
        information: it is how you check that a figure was measured rather than
        remembered, and how an analyst tells a provider outage apart from a chain
        that genuinely stopped. None of it helps decide whether a wallet can be
        traced here, so it is one disclosure rather than three permanent rows.
      */}
      <Disclosure label="Provider and timing" className="mt-1" bodyClassName="text-xs">
        <dl className="divide-y">
          <ValueRow label="Provider" mono={false}>
            {entry?.provider || null}
          </ValueRow>
          <ValueRow
            label="Checked at"
            mono={false}
            reason="Every figure above was fetched on this request and is not cached."
          >
            {entry?.checked_at ? formatDateTime(entry.checked_at) : null}
          </ValueRow>
        </dl>
      </Disclosure>

      {Array.isArray(entry?.evidence_notes) && entry.evidence_notes.length ? (
        <ul className="mt-4 space-y-2 border-t pt-3 text-xs leading-5 text-muted-foreground">
          {entry.evidence_notes.map((n, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden="true">—</span>
              <span>{n}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  );
}

export default function Network() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .networkOverview()
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const chains = Array.isArray(data?.chains) ? data.chains : [];
  const reachable = chains.filter((c) => c?.available).length;

  return (
    <div className="space-y-8 px-6 py-8">
      <PageHeader
        eyebrow="Network"
        title="Which chains this deployment can trace"
        description="Checked live against the providers BlockTrace queries. A chain that is reachable here can be traced end to end; a chain that is not will report a provider problem rather than an empty result."
        actions={
          <Button
            variant="outline"
            onClick={load}
            disabled={loading}
            title="Re-query every chain now. Nothing on this page updates on its own."
          >
            <RefreshCw
              data-icon="inline-start"
              className={loading ? "animate-spin" : undefined}
            />
            {loading ? "Checking…" : "Refresh"}
          </Button>
        }
      />

      {error ? <ErrorPanel error={error} onRetry={load} /> : null}

      {loading && !data ? (
        <LoadingBlock label="Querying providers" />
      ) : data ? (
        <>
          {reachable < chains.length ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              <p className="font-medium">
                {chains.length - reachable} of {chains.length} chains did not
                respond.
              </p>
              <p className="mt-1 text-xs opacity-90">
                Their cells below read &ldquo;not available&rdquo; rather than
                zero. A provider that could not be reached says nothing about
                the chain, and a block height of 0 would be a statement about
                the chain that no one has evidence for.
              </p>
            </div>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-2">
            {chains.map((entry) => (
              <ChainCard
                key={entry?.chain || entry?.chain_name}
                entry={entry}
              />
            ))}
          </div>

          <SectionCard title="How to read this page">
            <p className="text-sm leading-6 text-muted-foreground">
              {data.note}
            </p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              This page does not poll. A value that changed under the reader
              would have no timestamp the reader could check, so nothing updates
              until you refresh.
            </p>
            {data.checked_at ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Fetched at {formatDateTime(data.checked_at)}.
              </p>
            ) : null}
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}
