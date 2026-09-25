/**
 * Dashboard — the investigation overview, on the imported Dashboard 01 layout.
 *
 * The layout is the shadcn block's: a `SectionCards` stat row, a
 * `ChartAreaInteractive` timeline, and a table of recent cases. The numbers are
 * not the block's. The block arrived with "Total Revenue $1,250.00" and 120 rows
 * of invented visitor traffic, which in a forensic console would be a claim
 * about evidence that nothing measured.
 *
 * Every figure below is read from `/analytics/overview` and
 * `/investigations`, or shown as unavailable. The `data_basis` note is always
 * on screen, because the denominator is the whole point: these are statistics
 * over the investigations this account has run, never over a chain.
 *
 * `pages/dashboard.jsx` is the previous layout. It is untouched and still
 * builds; it is simply not routed.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";

import { ChartAreaInteractive } from "@/components/chart-area-interactive";
import { SectionCards } from "@/components/section-cards";
import {
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  PageHeader,
  RiskBadge,
} from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import { NOT_AVAILABLE, chainLabel, formatCount, formatDateTime } from "@/lib/format";

/**
 * How many recent cases the table shows. The same limit the previous overview
 * page used, so the endpoint behaves identically.
 */
const RECENT_LIMIT = 5;

/** A count is only a count if the API reported one. `0` is a real answer. */
function count(n) {
  return typeof n === "number" ? formatCount(n) : null;
}

export default function Dashboard01() {
  const { isDemo } = useAuth();
  const [overview, setOverview] = useState(null);
  const [recent, setRecent] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    // The same two calls the previous overview page made. `risk-trend` is not
    // requested: the chart plots `overview.timeline.by_day`, which is a
    // per-day count of real investigations and already covers the same period
    // with a unit the block's chart can label honestly.
    Promise.allSettled([
      api.analyticsOverview(),
      api.investigations({ limit: RECENT_LIMIT }),
    ]).then(([o, r]) => {
      if (cancelled) return;
      setOverview(o.status === "fulfilled" ? o.value : null);
      setRecent(r.status === "fulfilled" ? r.value : null);
      if (o.status === "rejected") setErr(o.reason);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const data = overview || {};
  const basis = data.data_basis || {};

  /**
   * The four tiles.
   *
   * `SectionCards` renders `NOT_AVAILABLE` for a null value, so each field is
   * passed through as-is: a field the backend did not report becomes an
   * explicit gap rather than a zero, because "0 investigations" and "the
   * overview call did not return this" are different facts.
   *
   * The dependencies are the individual fields rather than `basis`, `entities`
   * and `reports`, because those are objects rebuilt on every render and would
   * make this memo useless.
   */
  const investigationCount = basis.investigation_count;
  const analysedHere = basis.analysed_here;
  const transactionsInspected = basis.transactions_inspected;
  const source = basis.source;
  const distinctNames = data.entities?.distinct_names;
  const reportsGenerated = data.reports?.generated;

  const stats = useMemo(
    () => [
      {
        label: "Investigations",
        value: count(investigationCount),
        note:
          typeof analysedHere === "number"
            ? `Analysed here: ${formatCount(analysedHere)}`
            : "Analysed count not reported",
      },
      {
        label: "Transactions inspected",
        value: count(transactionsInspected),
        note: source ? `Source: ${source}` : "From saved investigations only",
      },
      {
        label: "Distinct entities (attributed)",
        value: count(distinctNames),
        note: "Named entities in your saved results",
      },
      {
        // `reports` is a sibling of `data_basis`, not a field inside it.
        label: "Reports generated",
        value: count(reportsGenerated),
        note: "PDF dossiers written for your cases",
      },
    ],
    [
      investigationCount,
      analysedHere,
      transactionsInspected,
      source,
      distinctNames,
      reportsGenerated,
    ],
  );

  /**
   * The chart series.
   *
   * `timeline.by_day` is `[{date, count}]` in `YYYY-MM-DD`, oldest first. It is
   * mapped to a single `investigations` key so the area is labelled with what
   * it measures. The chart anchors its 7/30/90-day window to the newest point,
   * so a gap in the record shortens the visible range instead of emptying it.
   */
  const byDay = data.timeline?.by_day;
  const timeline = useMemo(
    () =>
      (Array.isArray(byDay) ? byDay : [])
        .filter((p) => p?.date && typeof p.count === "number")
        .map((p) => ({ date: p.date, investigations: p.count })),
    [byDay],
  );

  const recentItems = Array.isArray(recent?.items) ? recent.items : [];

  if (loading) {
    return (
      <div className="min-h-[60vh] px-6 py-10">
        <LoadingBlock label="Loading dashboard" />
      </div>
    );
  }

  if (err && !overview) {
    return (
      <div className="px-6 py-10">
        <ErrorPanel
          error={{ kind: err?.kind || "unavailable", detail: err?.message || String(err) }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Overview"
        title="Blockchain Intelligence Dashboard"
        description={
          basis.note ||
          "Statistics over the investigations you have saved. These describe your own cases, not the chain as a whole."
        }
        actions={
          <Button render={<Link to="/app/trace" />}>
            <Search data-icon="inline-start" />
            New trace
          </Button>
        }
      />

      {isDemo ? (
        <Badge
          variant="outline"
          className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
        >
          Demo mode — cases are not isolated between users.
        </Badge>
      ) : null}

      <SectionCards stats={stats} />

      <div className="px-4 lg:px-6">
        <ChartAreaInteractive
          data={timeline}
          series={["investigations"]}
          labels={{ investigations: "Investigations run" }}
          title="Investigations over time"
          caption="Cases you have run, by the day they were saved"
          emptyMessage="No saved investigations yet. Run a trace to populate this chart."
        />
      </div>

      <div className="px-4 lg:px-6">
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">Recently saved</h2>
          <Link
            to="/app/investigations"
            className="text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            All investigations
          </Link>
        </div>

        {recentItems.length > 0 ? (
          <div className="overflow-hidden rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Case</TableHead>
                  <TableHead>Chain</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead className="whitespace-nowrap">Saved</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentItems.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell>
                      <Link
                        to={`/app/investigations/${encodeURIComponent(inv.id)}`}
                        className="block min-w-0"
                      >
                        <span className="block truncate text-sm font-medium">
                          {inv.title || inv.seed || "Untitled"}
                        </span>
                        <span className="block truncate font-mono text-[11px] text-muted-foreground">
                          {inv.seed || NOT_AVAILABLE}
                        </span>
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {inv.chain_name || chainLabel(inv.chain) || inv.chain || NOT_AVAILABLE}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <RiskBadge level={inv.risk_level} score={inv.risk_score} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {inv.created_at ? formatDateTime(inv.created_at) : NOT_AVAILABLE}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState
            title="No investigations saved"
            description="Trace a wallet or transaction to begin."
            action={<Button render={<Link to="/app/trace" />}>Trace now</Button>}
          />
        )}
      </div>

      <section className="rounded-xl border bg-card/50 p-4 text-xs leading-6 text-muted-foreground">
        <p>
          <strong className="text-foreground">What this describes:</strong>{" "}
          {basis.source || "Your saved investigations."}{" "}
          {basis.note ||
            "These statistics describe your own cases, not the chain's state."}
        </p>
        <p className="mt-1">
          <strong className="text-foreground">What it does not describe:</strong> chain-wide
          metrics, market data, live provider status, or any figure from outside this
          account's traces.
        </p>
      </section>
    </div>
  );
}
