/**
 * The risk assessment.
 *
 * A score without its derivation is an oracle. This panel shows all three
 * parts of the assessment the engine produced:
 *
 *   score   how high
 *   basis   which indicators contributed, and what each one is worth
 *   limits  what the score does *not* cover
 *
 * The three are kept visually separate because they have different authority.
 * The indicators are the finding. The score is a summary. The limits are what
 * stops the summary being over-read, and they are the part most often left off.
 *
 * The engine's own `assessment` sentence is rendered verbatim above the
 * breakdown. It is not summarised, because a paraphrase of a conclusion is a
 * new conclusion, and this one has not been reviewed.
 */

import { useMemo } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  RiskBadge,
  ScoreBar,
  SectionCard,
  SeverityChip,
  Value,
} from "@/components/common";
import { riskTone, severityLabel, truncateHash } from "@/lib/format";

/**
 * What each indicator weight means, so an operator does not have to guess why
 * "high" is 62 and not 70.
 *
 * The key is the indicator's `code`, which is the engine's stable machine
 * identifier. An indicator whose code is not listed here still renders — it
 * just says its weight without a legend, rather than being hidden.
 */
const WEIGHT_NOTES = {
  sanctioned_counterparty:
    "A transfer touched an address that the cited source lists as sanctioned.",
  mixer_interaction:
    "A transfer touched an address attributed to a mixing service.",
  rapid_sequencing:
    "Value moved through the subject in a pattern consistent with layering.",
  high_value_transfer:
    "A transfer exceeded the chain's typical size for this subject.",
  unclassified_destination:
    "Value left for an address with no attribution at all.",
  exchange_hopping:
    "Value moved between several exchange addresses, which is common in both laundering and ordinary trading.",
  self_transfer:
    "The subject sent to itself, which has no purpose in ordinary use.",
  dust_pattern:
    "Many very small transfers, which is what address-rotation poisoning looks like.",
};

/** One indicator: what it is, why it fired, and what it cost the score. */
function Indicator({ indicator }) {
  const evidence = indicator.evidence;
  return (
    <li className="rounded-md border bg-card px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityChip severity={indicator.severity} />
        <span className="text-sm font-medium">
          {indicator.name || indicator.code}
        </span>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          +{indicator.weight}
        </span>
      </div>

      {evidence ? (
        <p className="mt-1.5 text-xs leading-5 text-muted-foreground">{evidence}</p>
      ) : (
        <p className="mt-1.5 text-xs leading-5 text-amber-700 dark:text-amber-400">
          This indicator fired without recording why. Treat it as unsupported
          until the engine records evidence for it.
        </p>
      )}

      {WEIGHT_NOTES[indicator.code] ? (
        <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
          {WEIGHT_NOTES[indicator.code]}
        </p>
      ) : null}

      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
        {indicator.source ? <span>Source: {indicator.source}</span> : null}
        {indicator.related_addresses?.length ? (
          <span>
            Addresses:{" "}
            {indicator.related_addresses
              .slice(0, 3)
              .map((a) => truncateHash(a, 8, 6))
              .join(", ")}
            {indicator.related_addresses.length > 3
              ? ` +${indicator.related_addresses.length - 3} more`
              : ""}
          </span>
        ) : null}
        {indicator.related_transactions?.length ? (
          <span>
            Transactions:{" "}
            {indicator.related_transactions
              .slice(0, 2)
              .map((h) => truncateHash(h, 8, 6))
              .join(", ")}
          </span>
        ) : null}
      </div>
    </li>
  );
}

export function RiskPanel({ risk, className = "" }) {
  const assessment = risk || {};
  const indicators = useMemo(
    () => (Array.isArray(assessment.indicators) ? assessment.indicators : []),
    [assessment.indicators],
  );
  const breakdown = assessment.score_breakdown || {};
  const level = assessment.risk_level;
  const score = typeof assessment.risk_score === "number" ? assessment.risk_score : null;
  const tone = riskTone(level);

  const Icon = level === "UNKNOWN" ? ShieldQuestion : tone === "negative" ? ShieldAlert : ShieldCheck;

  // When the run failed to reach a provider, an engine that still emits a
  // score is describing a graph it did not complete. Say so above the number.
  const unassessable = indicators.length === 0;

  return (
    <SectionCard
      title="Risk assessment"
      description="Produced by one shared engine for every chain. The score is a summary; the indicators underneath it are the finding."
      className={className}
      bodyClassName="space-y-4"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <Icon
            className={`mt-0.5 size-5 shrink-0 ${
              tone === "negative"
                ? "text-red-600 dark:text-red-400"
                : tone === "caution" || tone === "caution-strong"
                  ? "text-amber-600 dark:text-amber-400"
                  : tone === "positive"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-muted-foreground"
            }`}
            aria-hidden="true"
          />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <RiskBadge level={level} score={score} />
              {unassessable ? (
                <Badge variant="outline" className="border-border bg-muted text-muted-foreground">
                  No indicators
                </Badge>
              ) : null}
            </div>
            {assessment.assessment ? (
              <p className="mt-2 max-w-2xl text-sm leading-6">{assessment.assessment}</p>
            ) : (
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                The engine did not record an assessment sentence for this run.
              </p>
            )}
          </div>
        </div>

        <div className="w-full sm:w-56">
          <ScoreBar score={score} max={100} label="risk score" tone={tone} />
        </div>
      </div>

      {unassessable ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          No risk indicators were raised. That is not a clean bill of health:
          it means nothing in the data the providers returned matched a rule in
          the engine. If this run ended in a provider failure or was truncated,
          the absence of indicators reflects what was never seen.
        </p>
      ) : null}

      {indicators.length > 0 ? (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Indicators ({indicators.length})
          </h3>
          <ul className="mt-2 space-y-2">
            {indicators.map((ind, i) => (
              <Indicator key={`${ind.code}-${i}`} indicator={ind} />
            ))}
          </ul>
        </div>
      ) : null}

      {Object.keys(breakdown).length > 0 ? (
        <details className="rounded-md border px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium">
            How the score was reached
          </summary>
          <dl className="mt-2 space-y-1">
            {Object.entries(breakdown).map(([code, contribution]) => (
              <div key={code} className="flex items-baseline justify-between gap-3 text-xs">
                <dt className="text-muted-foreground">{code}</dt>
                <dd className="font-mono">
                  <Value>{contribution}</Value>
                </dd>
              </div>
            ))}
            <div className="flex items-baseline justify-between gap-3 border-t pt-1 text-xs font-medium">
              <dt>Total</dt>
              <dd className="font-mono">
                <Value>{score}</Value>
              </dd>
            </div>
          </dl>
          <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
            The engine's own accounting, shown as it recorded it. If the total
            above does not match the score, the discrepancy is in the engine,
            not a rounding artefact.
          </p>
        </details>
      ) : null}

      <p className="text-[10px] leading-4 text-muted-foreground">
        A risk score describes the data that was returned for this run. It is
        not a legal judgement, not a compliance determination, and not evidence
        that any address is controlled by any person. Verify against the cited
        sources before acting on it.
        {indicators.length
          ? ` Indicators shown: ${indicators
              .map((i) => `${i.name || i.code} (${severityLabel(i.severity).toLowerCase()})`)
              .join(", ")}.`
          : null}
      </p>
    </SectionCard>
  );
}

export default RiskPanel;
