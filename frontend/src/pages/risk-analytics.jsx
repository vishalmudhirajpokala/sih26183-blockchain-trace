/**
 * Risk analytics — aggregate statistics over *your own* investigations.
 *
 * The single most important thing on this page is the denominator, so
 * `data_basis` is rendered permanently rather than hidden behind a tooltip. The
 * backend computes these numbers from saved cases and says so in the payload;
 * if the UI dropped that note, a risk histogram of 12 cases would read like a
 * market-wide risk distribution, which it is not.
 *
 * Averages are also guarded: with fewer than a handful of cases, a mean score
 * is arithmetically exact and analytically useless, so it is shown with its
 * sample size rather than presented as a finding.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity } from "lucide-react";

import { api } from "@/lib/api";
import {
  chainLabel,
  entityTypeClass,
  entityTypeLabel,
  formatCount,
  formatDateTime,
  riskBadgeClass,
  statusInfo,
} from "@/lib/format";
import {
  EmptyState,
  ErrorPanel,
  LoadingBlock,
  NotAvailable,
  PageHeader,
  RiskBadge,
  ScoreBar,
  SectionCard,
  StatGrid,
  ValueRow,
} from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** A mean over fewer cases than this is noise dressed as a statistic. */
const THIN_SAMPLE = 5;

function CountRow({ label, count, total, className }) {
  const share = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className={className}>{label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {formatCount(count)} · {share}%
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-foreground/70"
          style={{ width: `${share}%` }}
        />
      </div>
    </div>
  );
}

export default function RiskAnalytics() {
  const [overview, setOverview] = useState(null);
  const [trend, setTrend] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([api.analyticsOverview(), api.riskTrend()])
      .then(([o, t]) => {
        setOverview(o);
        setTrend(t);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !overview) {
    return (
      <div className="px-6 py-8">
        <LoadingBlock label="Loading analytics" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 px-6 py-8">
        <PageHeader eyebrow="Analytics" title="Risk analytics" />
        <ErrorPanel error={error} onRetry={load} />
      </div>
    );
  }

  if (!overview) return null;

  const basis = overview.data_basis || {};
  const risk = overview.risk || {};
  const distribution = overview.distribution || {};
  const timeline = overview.timeline || {};
  const entities = overview.entities || {};
  const reports = overview.reports || {};

  const analysed = basis.analysed_here ?? 0;
  const scores = Array.isArray(risk.scores) ? risk.scores : [];
  const byLevel = risk.by_level || {};
  const byChain = distribution.by_chain || {};
  const byStatus = distribution.by_status || {};
  const byEntityType = distribution.by_entity_type || {};
  const byDay = Array.isArray(timeline.by_day) ? timeline.by_day : [];
  const points = Array.isArray(trend?.points) ? trend.points : [];

  // The risk trend is drawn from the risk-scored subset only. A point whose
  // score is absent is not plotted as zero — that would invent a measurement.
  const scored = points.filter(
    (p) => typeof p?.risk_score === "number" && p.risk_score > 0,
  );
  const maxScore = scored.reduce((m, p) => Math.max(m, p.risk_score), 0);
  const peak = byDay.length
    ? byDay.reduce((a, b) => (b.count > a.count ? b : a))
    : null;

  return (
    <div className="space-y-8 px-6 py-8">
      <PageHeader
        eyebrow="Analytics"
        title="Risk analytics"
        description="Aggregate view over the investigations you have run. These are statistics about your cases, not about any chain or market."
        actions={
          <Button variant="outline" render={<Link to="/app/investigations" />}>
            View investigations
          </Button>
        }
      />

      {analysed === 0 ? (
        <EmptyState
          icon={Activity}
          title="No investigations to analyse"
          description="Analytics are computed from saved investigations. Once you run and save a trace, its risk score, chain, and attributed entity are counted here."
          action={
            <Button render={<Link to="/app/trace" />}>Run a trace</Button>
          }
        />
      ) : (
        <>
          <StatGrid
            items={[
              {
                label: "Cases analysed",
                value: formatCount(analysed),
                tooltip: "Cases included in the figures below.",
              },
              {
                label: "Cases on record",
                value: formatCount(basis.investigation_count ?? 0),
                tooltip: "Total saved cases for this account.",
              },
              {
                label: "Transactions inspected",
                value: formatCount(basis.transactions_inspected ?? 0),
                tooltip: "Summed across the analysed cases.",
              },
              {
                label: "Dossiers generated",
                value: formatCount(reports.generated ?? 0),
              },
            ]}
          />

          <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
            <div className="min-w-0 space-y-6">
              <SectionCard
                title="Risk distribution"
                description="How the analysed cases fall across risk levels."
              >
                {Object.keys(byLevel).length === 0 ? (
                  <NotAvailable reason="No case in this set carries a risk level." />
                ) : (
                  <div className="space-y-4">
                    {Object.entries(byLevel)
                      .sort((a, b) => b[1] - a[1])
                      .map(([level, count]) => (
                        <div key={level} className="flex items-center gap-3">
                          <RiskBadge level={level} />
                          <CountRow
                            label={statusInfo(level).short || String(level)}
                            count={count}
                            total={analysed}
                          />
                        </div>
                      ))}
                  </div>
                )}
              </SectionCard>

              <SectionCard
                title="Risk score over time"
                description="Each case's score in the order it was saved. This is a record of your own runs, not a market index."
              >
                {scored.length === 0 ? (
                  <NotAvailable
                    reason="No case has a recorded risk score, so there is no series to plot."
                  />
                ) : (
                  <div className="space-y-3">
                    {/* A plain bar series, not a smoothed line: the values are
                        discrete case scores, and a curve between them would
                        imply a measurement that was never taken. */}
                    <div className="flex h-40 items-end gap-1 overflow-x-auto pb-1">
                      {scored.map((p) => (
                        <div
                          key={p.id}
                          className="min-w-[6px] flex-1"
                          title={`${p.seed || p.id} · score ${p.risk_score} · ${p.risk_level} · ${formatDateTime(p.created_at)}`}
                        >
                          <div
                            className={`w-full rounded-t ${riskBadgeClass(p.risk_level)}`}
                            style={{
                              height: `${Math.max(
                                4,
                                maxScore > 0
                                  ? (p.risk_score / maxScore) * 140
                                  : 0,
                              )}px`,
                            }}
                          />
                        </div>
                      ))}
                    </div>
                    <div className="flex justify-between text-[11px] text-muted-foreground">
                      <span>{formatDateTime(scored[0].created_at)}</span>
                      <span>
                        {scored.length} scored case
                        {scored.length === 1 ? "" : "s"}
                      </span>
                      <span>{formatDateTime(scored[scored.length - 1].created_at)}</span>
                    </div>
                  </div>
                )}
              </SectionCard>

              <div className="grid gap-6 md:grid-cols-2">
                <SectionCard title="By chain">
                  {Object.keys(byChain).length === 0 ? (
                    <NotAvailable reason="No chain recorded." />
                  ) : (
                    <div className="space-y-4">
                      {Object.entries(byChain)
                        .sort((a, b) => b[1] - a[1])
                        .map(([c, count]) => (
                          <CountRow
                            key={c}
                            label={chainLabel(c) || c}
                            count={count}
                            total={analysed}
                          />
                        ))}
                    </div>
                  )}
                </SectionCard>

                <SectionCard title="By case status">
                  {Object.keys(byStatus).length === 0 ? (
                    <NotAvailable reason="No status recorded." />
                  ) : (
                    <div className="space-y-4">
                      {Object.entries(byStatus)
                        .sort((a, b) => b[1] - a[1])
                        .map(([s, count]) => (
                          <CountRow
                            key={s}
                            label={statusInfo(s).short || s}
                            count={count}
                            total={analysed}
                          />
                        ))}
                    </div>
                  )}
                </SectionCard>
              </div>

              {Object.keys(byEntityType).length > 0 ? (
                <SectionCard
                  title="Strongest attributions by type"
                  description="The entity type recorded on each case's best-sourced attribution."
                >
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(byEntityType)
                      .sort((a, b) => b[1] - a[1])
                      .map(([type, count]) => (
                        <Badge
                          key={type}
                          variant="outline"
                          className={entityTypeClass(type)}
                        >
                          {entityTypeLabel(type)} · {count}
                        </Badge>
                      ))}
                  </div>
                </SectionCard>
              ) : null}
            </div>

            <aside className="space-y-6">
              <SectionCard title="What this data is">
                <ValueRow label="Source">{basis.source || null}</ValueRow>
                <ValueRow label="Cases analysed" mono>
                  {formatCount(analysed)}
                </ValueRow>
                <ValueRow label="Cases on record" mono>
                  {formatCount(basis.investigation_count ?? 0)}
                </ValueRow>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  {basis.note}
                </p>
              </SectionCard>

              <SectionCard title="Score summary">
                {scores.length === 0 ? (
                  <NotAvailable reason="No scores recorded." />
                ) : (
                  <>
                    <ValueRow
                      label="Average"
                      reason={
                        analysed < THIN_SAMPLE
                          ? `A mean over ${analysed} case${analysed === 1 ? "" : "s"} is arithmetically exact but analytically thin.`
                          : null
                      }
                    >
                      {risk.average !== null ? risk.average : null}
                    </ValueRow>
                    <ValueRow label="Highest">{risk.max ?? null}</ValueRow>
                    <ValueRow label="Lowest">{risk.min ?? null}</ValueRow>
                    {risk.average !== null ? (
                      <ScoreBar
                        score={risk.average}
                        label={`Mean score across ${scores.length} cases`}
                      />
                    ) : null}
                  </>
                )}
              </SectionCard>

              {peak ? (
                <SectionCard title="Case volume">
                  <ValueRow label="Busiest day" mono>
                    {peak.date}
                  </ValueRow>
                  <ValueRow label="Cases that day" mono>
                    {formatCount(peak.count)}
                  </ValueRow>
                  {byDay.length > 1 ? (
                    <ValueRow label="Days with cases" mono>
                      {formatCount(byDay.length)}
                    </ValueRow>
                  ) : null}
                </SectionCard>
              ) : null}

              {entities.distinct_names ? (
                <SectionCard title="Attributed entities">
                  <ValueRow label="Cases with an attribution" mono>
                    {formatCount(entities.attributed_investigations ?? 0)}
                  </ValueRow>
                  <ValueRow label="Distinct names" mono>
                    {formatCount(entities.distinct_names ?? 0)}
                  </ValueRow>
                  {Array.isArray(entities.names) && entities.names.length ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {entities.names.map((n) => (
                        <Badge key={n} variant="secondary" className="text-[11px]">
                          {n}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </SectionCard>
              ) : null}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
