/**
 * Dashboard — the BlockTrace overview, on the shadcn dashboard-01 layout.
 *
 * The composition is the block's, in the block's order: a page header, the
 * `SectionCards` stat row, the `ChartAreaInteractive` timeline, and a table of
 * recent cases. The tokens, radius scale, type stack and chart colours all come
 * from the `base-nova` theme in `index.css`, which is the theme
 * `npx shadcn@latest add dashboard-01` is built against, so this page is the
 * same design system rather than something modelled on it.
 *
 * The data is the only thing that is BlockTrace's, and it is the same data the
 * overview page has always read:
 *
 *   api.analyticsOverview()   -> the four stat tiles and the daily timeline
 *   api.riskTrend()           -> the most recent saved case's risk score
 *   api.investigations(...)   -> the recent-cases table
 *
 * Nothing here is invented. The block arrived carrying "Total Revenue
 * $1,250.00", 92 rows of April-2024 visitor traffic and a hard-coded
 * `2024-06-30` window anchor; all of that is gone. A counter the API did not
 * report renders as `Not available`, because "0 investigations" and "the
 * overview call did not return this field" are different facts and only one of
 * them is a measurement.
 *
 * The Dashboard 01 demo `DataTable` is deliberately not mounted. It models
 * reviewer assignment, targets and limits — none of which exist here — so the
 * table below is built from the same `ui/table` primitives the real
 * investigations page uses.
 *
 * `pages/dashboard.jsx` is the previous layout. It is untouched, still builds,
 * and is not routed.
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
import { api } from "@/lib/api";
import { NOT_AVAILABLE, chainLabel, formatCount, formatDateTime } from "@/lib/format";

/** How many recent cases the table shows, as the previous overview page used. */
const RECENT_LIMIT = 5;

/**
 * A count is only a count if the API reported one.
 *
 * `0` is a real answer and is formatted. `undefined` means the field was absent
 * and becomes `null`, which `SectionCards` renders as `Not available`.
 */
function count(n) {
  return typeof n === "number" ? formatCount(n) : null;
}

export default function Dashboard01() {
  const [overview, setOverview] = useState(null);
  const [trend, setTrend] = useState(null);
  const [recent, setRecent] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    Promise.allSettled([
      api.analyticsOverview(),
      api.riskTrend(),
      api.investigations({ limit: RECENT_LIMIT }),
    ]).then(([o, t, r]) => {
      if (cancelled) return;
      setOverview(o.status === "fulfilled" ? o.value : null);
      setTrend(t.status === "fulfilled" ? t.value : null);
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

  // The individual fields rather than `basis` / `entities` / `reports`, because
  // those are objects rebuilt on every render and would defeat the memo.
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
        label: "Transactions Inspected",
        value: count(transactionsInspected),
        note: source ? `Source: ${source}` : "From saved investigations only",
      },
      {
        label: "Attributed Entities",
        value: count(distinctNames),
        // Spelled "Attributed" rather than "Distinct" because the figure counts
        // addresses a real source has *named*, not every distinct address seen.
        // "Distinct" reads as "how many addresses were in my investigations",
        // which this is not -- so a zero would look like the investigations
        // themselves were empty. A zero here means no address could be named.
        note: count(distinctNames)
          ? "Addresses a real source named, across your saved results"
          : "No address could be named here. Addresses in your investigations are still traced, graphed and scored.",
      },
      {
        // `reports` is a sibling of `data_basis`, not a field inside it.
        label: "Reports Generated",
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
   * `timeline.by_day` is `[{date, count}]` in `YYYY-MM-DD`, oldest first, and is
   * mapped to a single `investigations` key so the area is labelled with what it
   * measures. `ChartAreaInteractive` anchors its 7d/30d/90d window to the newest
   * point, so a gap in the record shortens the visible range instead of
   * emptying the chart or padding it with synthetic days.
   */
  const byDay = data.timeline?.by_day;
  const timeline = useMemo(
    () =>
      (Array.isArray(byDay) ? byDay : [])
        .filter((p) => p?.date && typeof p.count === "number")
        .map((p) => ({ date: p.date, investigations: p.count })),
    [byDay],
  );

  /**
   * The newest saved case's risk, from the real trend endpoint.
   *
   * `risk-trend` returns points oldest-first, so the last one with a numeric
   * score is the most recent case that actually carries one. Reported as-is;
   * when the endpoint is empty this is `null` and the line says so.
   */
  const latestRisk = useMemo(() => {
    const points = Array.isArray(trend?.points) ? trend.points : [];
    for (let i = points.length - 1; i >= 0; i -= 1) {
      if (typeof points[i]?.risk_score === "number") return points[i];
    }
    return null;
  }, [trend]);

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
    <div className="space-y-6">
      {/*
        `PageHeader` renders the block's page header verbatim: a flex row that
        stacks on small screens, `md:items-end md:justify-between` on large ones,
        with the title and its muted description in a `space-y-1` stack.
      */}
      <PageHeader
        eyebrow="Overview"
        title="Your investigations"
        description={
          basis.note ||
          "Every figure below comes from investigations you have saved on this deployment. Paste a wallet or transaction on the Trace page to start one."
        }
        actions={
          <Button size="lg" render={<Link to="/app/trace" />}>
            <Search data-icon="inline-start" />
            Trace a wallet
          </Button>
        }
      />

      <SectionCards stats={stats} />

      {/*
        The block lays these sections out with the shell's own `gap`, and
        `SectionCards` brings its own `px-4 lg:px-6`, so the chart and the table
        are inset to the same measure rather than re-padded.
      */}
      <div className="px-4 lg:px-6">
        <ChartAreaInteractive
          data={timeline}
          series={["investigations"]}
          labels={{ investigations: "Investigations run" }}
          title="Investigations over time"
          caption="Cases you have run, by the day they were saved"
          captionShort="By day saved"
          emptyMessage="No saved investigations yet. Run a trace to populate this chart."
        />
      </div>

      <div className="px-4 lg:px-6">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-lg font-semibold tracking-tight">Recently saved</h2>
          <div className="flex items-baseline gap-3 text-sm">
            <span className="text-muted-foreground">
              {latestRisk
                ? `Latest risk ${latestRisk.risk_level ?? NOT_AVAILABLE} (${latestRisk.risk_score}/100)`
                : "Latest risk score not available"}
            </span>
            <Link
              to="/app/investigations"
              className="text-muted-foreground underline-offset-4 hover:underline"
            >
              All investigations
            </Link>
          </div>
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

      {/*
        Kept from the previous overview page. This is a forensic console: the
        denominator behind every number above has to stay on screen, or "12
        investigations" reads as a statement about the chain rather than about
        one operator's own cases.
      */}
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
