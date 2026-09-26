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

import { useMemo, useState } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Disclosure,
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

/**
 * One indicator, as a scannable row with its derivation behind a toggle.
 *
 * The name and the weight are the finding and stay on the surface. The evidence
 * paragraph is three or four sentences of genuine analysis, and with two or more
 * indicators permanently expanded it pushed everything below -- the graph, the
 * ledger -- off the first screen. So the reasoning is still present, still
 * attributed, and still one keystroke away, but it is not what you read first.
 */
function Indicator({ indicator, origin }) {
  const [showDetail, setShowDetail] = useState(false);
  const evidence = indicator.evidence;
  const hasDetail = Boolean(
    evidence ||
      WEIGHT_NOTES[indicator.code] ||
      indicator.source ||
      indicator.related_addresses?.length ||
      indicator.related_transactions?.length,
  );

  return (
    <li className="rounded-md border bg-card">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <SeverityChip severity={indicator.severity} />
        <span className="min-w-0 flex-1 text-sm font-medium">
          {indicator.name || indicator.code}
        </span>
        {origin ? (
          <span
            className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground"
            title={
              origin.is_subject
                ? "Raised against the address you traced"
                : `Raised against a counterparty: ${(origin.addresses || [])
                    .slice(0, 2)
                    .join(", ")}`
            }
          >
            {origin.is_subject ? "Subject" : "Counterparty"}
          </span>
        ) : null}
        <span className="font-mono text-xs text-muted-foreground">
          +{indicator.weight}
        </span>
        {hasDetail ? (
          <button
            type="button"
            aria-expanded={showDetail}
            onClick={() => setShowDetail((v) => !v)}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            {showDetail ? "Hide detail" : "Details"}
          </button>
        ) : null}
      </div>

      {showDetail ? (
        <div className="border-t px-3 py-2.5">
          {evidence ? (
            <p className="text-xs leading-5 text-muted-foreground">{evidence}</p>
          ) : (
            <p className="text-xs leading-5 text-amber-700 dark:text-amber-400">
              This indicator fired without recording why. Treat it as unsupported
              until the engine records evidence for it.
            </p>
          )}

          {WEIGHT_NOTES[indicator.code] ? (
            <p className="mt-1.5 text-[10px] leading-4 text-muted-foreground">
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
        </div>
      ) : null}
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
  const attribution = useMemo(
    () => assessment.signal_attribution || null,
    [assessment.signal_attribution],
  );
  // Indicators are collapsed by code upstream, so a code is a safe key here.
  // Anything without a match simply gets no badge rather than a wrong one.
  const signalByCode = useMemo(() => {
    const map = {};
    for (const s of attribution?.signals || []) map[s.code] = s;
    return map;
  }, [attribution]);
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
            {/*
              The engine's own verdict sentence, verbatim and unparaphrased.
              A paraphrase of a conclusion is a new conclusion, and this one has
              not been reviewed.
            */}
            {assessment.assessment ? (
              <p className="mt-2 max-w-2xl text-sm leading-6">{assessment.assessment}</p>
            ) : (
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                The engine did not record an assessment sentence for this run.
              </p>
            )}
          </div>
        </div>

        {/*
          The bar is the score drawn as a proportion. `RiskBadge` already shows
          the number, so the bar carries no label -- "risk score" appeared twice
          in this block, once as the badge text and once as the bar caption.
        */}
        <div className="w-full sm:w-56">
          <ScoreBar score={score} max={100} tone={tone} />
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
            {indicators.length === 1
              ? "1 indicator detected"
              : `${indicators.length} indicators detected`}
          </h3>

          {/*
            Which address each signal is about.

            The score is one number attached to the traced address, but the
            signals in it are raised against whichever node in the graph showed
            the pattern, and that is often a counterparty. Shown here rather than
            buried because a reader who sees "CRITICAL 85" and cannot see where
            the signals came from will read it as four things known about the
            address they asked about -- a considerably stronger claim than the
            data supports. The scoring model is unchanged; this only makes the
            existing number legible.
          */}
          {attribution && attribution.total > 0 && attribution.counterparty > 0 ? (
            <p className="mt-1.5 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs leading-5">
              <span className="font-medium">
                {attribution.counterparty} of {attribution.total} signals
              </span>{" "}
              were raised against counterparty addresses, not the traced
              subject
              {attribution.subject > 0 ? (
                <>
                  {" "}({attribution.subject} concerned the subject itself)
                </>
              ) : null}
              . The score is an aggregate across the traced graph, so it is not a
              finding about the subject address on its own.
            </p>
          ) : null}

          <ul className="mt-2 space-y-1.5">
            {indicators.map((ind, i) => (
              <Indicator
                key={`${ind.code}-${i}`}
                indicator={ind}
                origin={signalByCode?.[ind.code]}
              />
            ))}
          </ul>
        </div>
      ) : null}

      {/*
        The engine's accounting, collapsed. It is real evidence -- it is how you
        check that a score of 45 is 25 plus 20 and not a number that arrived from
        nowhere -- but it is a derivation, not the finding, so it is not on the
        first screen.
      */}
      {Object.keys(breakdown).length > 0 ? (
        <Disclosure
          label="How was this score calculated"
          hint="the engine's own accounting"
          bodyClassName="text-xs"
        >
          <dl className="space-y-1">
            {Object.entries(breakdown).map(([code, contribution]) => (
              <div key={code} className="flex items-baseline justify-between gap-3 text-xs">
                <dt className="font-mono text-muted-foreground">{code}</dt>
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
            Shown as the engine recorded it. If the total does not match the score,
            the discrepancy is in the engine, not a rounding artefact.
          </p>
        </Disclosure>
      ) : null}

      {/*
        Methodology, collapsed. "One shared engine for every chain. The score is
        a summary; the indicators are the finding." was the card's permanent
        description, i.e. a note about how BlockTrace is built sat above the
        finding on every single investigation. It is true, useful, and not what
        an investigator opens the page to read, so it is a disclosure now.
      */}
      <Disclosure label="Risk methodology" bodyClassName="text-xs">
        <p className="leading-5 text-muted-foreground">
          One shared engine scores every chain, so a score means the same thing
          on TRON, Ethereum, BNB Smart Chain, Polygon and Bitcoin and is directly
          comparable between them. The score is a summary of the indicators
          below it; the indicators are the finding, and the weight each one
          carries is the engine&apos;s own.
        </p>
        <p className="mt-2 leading-5 text-muted-foreground">
          The score describes only the data the providers returned for this run.
          It is recalculated from the stored result, never carried over from an
          earlier trace, and it is not edited by hand.
        </p>
      </Disclosure>

      {/*
        The limits of the number, collapsed. This is the part most often left off
        a risk panel and the part that decides whether a reader over-reads it, so
        it is kept in full -- just not permanently in the way.
      */}
      <Disclosure label="About this risk score" bodyClassName="text-xs">
        <p className="leading-5 text-muted-foreground">
          A risk score describes the data that was returned for this run. It is
          not a legal judgement, not a compliance determination, and not evidence
          that any address is controlled by any person. Verify against the cited
          sources before acting on it.
        </p>
        {indicators.length ? (
          <p className="mt-2 leading-5 text-muted-foreground">
            Indicators shown:{" "}
            {indicators
              .map(
                (i) => `${i.name || i.code} (${severityLabel(i.severity).toLowerCase()})`,
              )
              .join(", ")}
            .
          </p>
        ) : null}
      </Disclosure>
    </SectionCard>
  );
}

export default RiskPanel;
