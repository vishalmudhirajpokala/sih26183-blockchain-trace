/**
 * Dashboard â€” the investigation overview.
 *
 * Every number is either read from `/analytics/overview` and `/analytics/risk-trend`
 * or explicitly shown as unavailable. No fabricated counts, no "live" metrics
 * the provider did not return, and the `data_basis.note` is always visible so
 * the reader never forgets what denominator these statistics describe.
 */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  PageHeader,
  StatCard,
  EmptyState,
  LoadingBlock,
  ErrorPanel,
  SectionCard,
} from "@/components/common";
import { api } from "@/lib/api";
import { chainLabel, formatCount, formatDateTime } from "@/lib/format";
import { useAuth } from "@/hooks/use-auth";

const LEVEL_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE", "UNKNOWN"];

export default function Dashboard() {
  const { isDemo } = useAuth();
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
      api.investigations({ limit: 5 }),
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
  const risk = data.risk || {};
  const dist = data.distribution || {};
  const basis = data.data_basis || {};

  const levelData = useMemo(() => {
    const counts = risk.by_level || {};
    return LEVEL_ORDER.map((lvl) => ({
      name: lvl,
      value: counts[lvl] || 0,
    })).filter((d) => d.value > 0);
  }, [risk.by_level]);

  const chainData = useMemo(() => {
    const counts = dist.by_chain || {};
    return Object.entries(counts)
      .map(([k, v]) => ({ name: chainLabel(k) || k, value: v }))
      .sort((a, b) => b.value - a.value);
  }, [dist.by_chain]);

  const trendPoints = (trend?.points || [])
    .filter((p) => typeof p.risk_score === "number")
    .slice(-30);

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
        <ErrorPanel error={{ kind: err?.kind || "unavailable", detail: err?.message || String(err) }} />
      </div>
    );
  }

  return (
    <div className="space-y-8 px-6 py-8">
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
        <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Demo mode â€” cases are not isolated between users.
        </Badge>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* StatCard renders "Not available" for a null value on its own, so the
            fallback is null rather than a wrapped element. */}
        <StatCard
          label="Investigations"
          value={basis.investigation_count ?? null}
          hint={
            basis.analysed_here !== null && basis.analysed_here !== undefined
              ? `Of which analysed here: ${formatCount(basis.analysed_here)}`
              : "Analysed count not reported"
          }
        />
        <StatCard
          label="Transactions inspected"
          value={basis.transactions_inspected ?? null}
          hint={basis.source ? `Source: ${basis.source}` : "From saved investigations only"}
        />
        <StatCard
          label="Distinct entities (attributed)"
          value={data.entities?.distinct_names ?? null}
        />
        {/* `reports` is a sibling of `data_basis`, not a field inside it. */}
        <StatCard
          label="Reports generated"
          value={data.reports?.generated ?? null}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <SectionCard title="Risk score distribution" description="Over saved investigations â€” not over the chain.">
          {levelData.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={levelData} barCategoryGap="20%">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    {levelData.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={
                          entry.name === "CRITICAL"
                            ? "#a34444"
                            : entry.name === "HIGH"
                              ? "#946200"
                              : entry.name === "MEDIUM"
                                ? "#356a9f"
                                : entry.name === "LOW"
                                  ? "#18734a"
                                  : "#94a5b7"
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No risk levels recorded" description="Run investigations to see scores distributed here." />
          )}
        </SectionCard>

        <SectionCard title="By chain" description="Where your investigations were run.">
          {chainData.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chainData} layout="vertical" barCategoryGap="20%">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
                  <YAxis dataKey="name" tick={{ fontSize: 11 }} width={70} />
                  <Tooltip />
                  <Bar dataKey="value" radius={[0, 6, 6, 0]} fill="#356a9f" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="No chain data" description="Investigations will appear here once saved." />
          )}
        </SectionCard>
      </div>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <SectionCard title="Risk trend" description="Score over the last runs (oldest first).">
          {trendPoints.length > 1 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendPoints}>
                  <defs>
                    <linearGradient id="rt" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#356a9f" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#356a9f" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="created_at" tickFormatter={(v) => (v ? String(v).slice(0, 10) : "")} tick={{ fontSize: 10 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip formatter={(v) => [String(v), "Score"]} />
                  <Area type="monotone" dataKey="risk_score" stroke="#356a9f" fill="url(#rt)" strokeWidth={2} dot={{ r: 3, fill: "#356a9f" }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState title="Not enough points" description="Run at least two traces with saved results to see a trend." />
          )}
        </SectionCard>

        <Card>
          <CardHeader>
            <CardTitle>Recently saved</CardTitle>
            <CardDescription>Newest first, up to 5.</CardDescription>
          </CardHeader>
          <CardContent>
            {recent?.items?.length ? (
              <ul className="divide-y">
                {recent.items.map((inv) => (
                  <li key={inv.id}>
                    <Link to={`/app/investigations/${encodeURIComponent(inv.id)}`} className="flex items-start gap-3 py-3 hover:underline">
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <p className="text-sm font-medium leading-snug truncate">{inv.title || inv.seed}</p>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Badge variant="outline">{inv.chain_name || chainLabel(inv.chain) || inv.chain}</Badge>
                          <span>{inv.risk_level}</span>
                          {inv.has_report ? <Badge variant="secondary">PDF</Badge> : null}
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground whitespace-nowrap">
                        {inv.created_at ? formatDateTime(inv.created_at) : "â€”"}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="No investigations saved"
                description="Trace a wallet or transaction to begin."
                action={
                  <Button render={<Link to="/app/trace" />}>Trace now</Button>
                }
              />
            )}
          </CardContent>
        </Card>
      </div>

      <section className="rounded-xl border bg-card/50 p-4 text-xs leading-6 text-muted-foreground">
        <p>
          <strong className="text-foreground">What this describes:</strong>{" "}
          {basis.source || "Your saved investigations."} {" "}
          {basis.note || "These statistics describe your own cases, not the chain's state."}
        </p>
        <p className="mt-1">
          <strong className="text-foreground">What it does not describe:</strong> chain-wide metrics,
          market data, live provider status, or any figure from outside this account's traces.
        </p>
      </section>
    </div>
  );
}

