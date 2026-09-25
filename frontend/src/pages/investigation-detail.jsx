/**
 * Investigation detail — the full record of one case.
 *
 * `GET /investigations/{id}` returns the stored row verbatim:
 *
 *   {id, title, notes, created_at, report_url, result}
 *
 * and `result` is a `TraceResult.to_dict()`: the same object the Trace Console
 * rendered when the case was run. Nothing here recomputes it. A stored
 * investigation is evidence, and evidence that is recalculated on display is no
 * longer evidence — so the counts, the risk score, and the graph all come from
 * the stored blob rather than from anything derived here.
 *
 * A 404 covers both "no such id" and "not yours". Those two are not
 * distinguished in the response, and this page does not try to guess which one
 * it hit.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { api, reportHref } from "@/lib/api";
import {
  chainLabel,
  formatDateTime,
  formatDuration,
  formatCount,
  safeSourceUrl,
} from "@/lib/format";
import {
  ErrorPanel,
  EvidenceNotes,
  LoadingBlock,
  PageHeader,
  ProviderLedger,
  RiskBadge,
  SectionCard,
  StatGrid,
  ValueRow,
} from "@/components/common";
import { RiskPanel } from "@/components/risk-panel";
import { FundFlowGraph } from "@/components/fund-flow-graph";
import { TransactionTable } from "@/components/transaction-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function InvestigationDetail() {
  const { id } = useParams();

  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [regenerating, setRegenerating] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .investigation(id)
      .then(setRecord)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function regenerate() {
    if (regenerating) return;
    setRegenerating(true);
    try {
      // This re-renders from the stored result. It does not re-trace, so the
      // graph in the dossier is the same graph on screen.
      const res = await api.regenerateReport(id);
      setRecord((prev) => (prev ? { ...prev, report_url: res.report_url } : prev));
      toast.success("Report re-rendered from the stored result.");
      toast.info(res.note);
    } catch (e) {
      toast.error(e.message || "The report could not be re-rendered.");
    } finally {
      setRegenerating(false);
    }
  }

  if (loading && !record) {
    return (
      <div className="px-6 py-8">
        <LoadingBlock label="Loading investigation" />
      </div>
    );
  }

  if (error) {
    // A 404 here means "missing or not yours". Saying which would confirm the
    // existence of another account's case, so the two are not separated.
    const missing = error.status === 404;
    return (
      <div className="space-y-6 px-6 py-8">
        <PageHeader
          eyebrow="Investigations"
          title={missing ? "Not available" : "Could not load this investigation"}
          actions={
            <Button variant="outline" render={<Link to="/app/investigations" />}>
              <ArrowLeft data-icon="inline-start" />
              All investigations
            </Button>
          }
        />
        {missing ? (
          <div className="rounded-lg border border-dashed p-6 text-sm leading-6 text-muted-foreground">
            <p>
              No investigation with this id is available to you. That covers two
              cases — the id does not exist, or it belongs to another account —
              and the response is identical for both so this page cannot
              confirm the existence of a case you are not permitted to read.
            </p>
          </div>
        ) : (
          <ErrorPanel error={error} onRetry={load} />
        )}
      </div>
    );
  }

  if (!record) return null;

  const result = record.result || {};
  const metadata = result.metadata || {};
  const risk = result.risk || {};
  const nodes = Array.isArray(result.nodes) ? result.nodes : [];
  const edges = Array.isArray(result.edges) ? result.edges : [];
  const transactions = Array.isArray(result.transactions) ? result.transactions : [];
  const notes = Array.isArray(result.evidence_notes) ? result.evidence_notes : [];
  const pdf = reportHref(record.report_url);
  // Provider-supplied, so scheme-checked before it becomes an href.
  const entitySourceUrl = safeSourceUrl(result.entity?.source_url);

  return (
    <div className="space-y-8 px-6 py-8">
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            <Link to="/app/investigations" className="hover:underline">
              Investigations
            </Link>
          </span>
        }
        title={record.title || record.id}
        description={
          result.status ? (
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{result.status}</Badge>
              {result.status_detail ? (
                <span className="text-sm text-muted-foreground">{result.status_detail}</span>
              ) : null}
            </span>
          ) : null
        }
        actions={
          <>
            {pdf ? (
              <Button render={<a href={pdf} target="_blank" rel="noopener noreferrer" />}>
                <Download data-icon="inline-start" />
                Download PDF
              </Button>
            ) : null}
            <Button
              variant="outline"
              onClick={regenerate}
              disabled={regenerating}
              title="Re-renders the PDF from the stored result. It does not re-run the trace, so the dossier cannot describe a different moment than this page."
            >
              <RefreshCw
                data-icon="inline-start"
                className={regenerating ? "animate-spin" : undefined}
              />
              {regenerating ? "Re-rendering…" : "Re-render PDF"}
            </Button>
          </>
        }
      />

      {/* A case that was cut short says so at the top, not in a footnote. */}
      {metadata.truncated ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <p className="font-medium">
            This trace stopped before it finished:{" "}
            {Array.isArray(metadata.truncation_reasons) && metadata.truncation_reasons.length
              ? metadata.truncation_reasons.join(" ")
              : "the engine reported truncation without naming a reason."}
          </p>
          <p className="mt-1 text-xs opacity-90">
            What is shown below is a partial graph. Absence of a counterparty in
            this result is not evidence that the subject did not transact with
            one.
          </p>
        </div>
      ) : null}

      <StatGrid
        items={[
          {
            label: "Risk",
            value: <RiskBadge level={risk.risk_level} score={risk.risk_score} />,
          },
          {
            label: "Chain",
            value: result.chain_name || chainLabel(result.chain) || result.chain,
          },
          {
            label: "Nodes",
            value: nodes.length,
            tooltip: "Addresses in the graph.",
          },
          {
            label: "Transactions",
            value: transactions.length,
            tooltip: "Normalized transfers in the ledger.",
          },
        ]}
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-6">
          <SectionCard
            title="Risk assessment"
            description="The engine's own assessment, shown with the evidence that produced it."
          >
            <RiskPanel risk={risk} />
          </SectionCard>

          <SectionCard
            title="Fund flow"
            description="Laid out by hop distance from the subject. Switch to 3D to rotate the same graph."
          >
            <FundFlowGraph
              nodes={nodes}
              edges={edges}
              transactions={transactions}
              chain={result.chain}
              seed={result.seed}
            />
          </SectionCard>

          <SectionCard
            title="Transaction ledger"
            description="Every normalized transfer, not only those in the graph."
          >
            <TransactionTable
              transactions={transactions}
              chain={result.chain}
              seed={result.seed}
            />
          </SectionCard>
        </div>

        <aside className="space-y-6">
          <SectionCard title="This case">
            <dl className="divide-y">
              <ValueRow label="Investigation id" mono copyable>
                {record.id}
              </ValueRow>
              <ValueRow label="Seed" mono copyable>
                {result.seed}
              </ValueRow>
              <ValueRow label="Input type">{result.input_type}</ValueRow>
              <ValueRow label="Status">{result.status}</ValueRow>
              <ValueRow label="Nodes examined">
                {formatCount(metadata.nodes_examined)}
              </ValueRow>
              <ValueRow label="Transactions inspected">
                {formatCount(metadata.transactions_inspected)}
              </ValueRow>
              <ValueRow label="Max depth reached">
                {typeof metadata.max_depth_reached === "number"
                  ? `${metadata.max_depth_reached} (limit ${metadata.depth_limit})`
                  : null}
              </ValueRow>
              <ValueRow label="Duration">
                {typeof metadata.duration_ms === "number"
                  ? formatDuration(metadata.duration_ms)
                  : null}
              </ValueRow>
              <ValueRow label="Saved">
                {record.created_at ? formatDateTime(record.created_at) : null}
              </ValueRow>
              <ValueRow label="PDF dossier" copyable={Boolean(record.report_url)}>
                {record.report_url ? record.report_url : null}
              </ValueRow>
            </dl>
          </SectionCard>

          {result.entity ? (
            <SectionCard
              title="Strongest attribution"
              description="The best-sourced label found anywhere in this trace."
            >
              <ValueRow label="Entity">{result.entity.name}</ValueRow>
              <ValueRow label="Type">{result.entity.type}</ValueRow>
              <ValueRow label="Source type">{result.entity.source_type}</ValueRow>
              <ValueRow label="Confidence">
                {typeof result.entity.confidence === "number"
                  ? result.entity.confidence
                  : null}
              </ValueRow>
              {entitySourceUrl ? (
                <ValueRow label="Source">
                  <a
                    href={entitySourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline underline-offset-4"
                  >
                    {entitySourceUrl}
                  </a>
                </ValueRow>
              ) : (
                <ValueRow
                  label="Source"
                  reason="This attribution carries no source URL, so it is shown as unverified."
                >
                  {null}
                </ValueRow>
              )}
            </SectionCard>
          ) : null}

          <ProviderLedger usage={metadata.provider_usage} />
        </aside>
      </div>

      <EvidenceNotes notes={notes} />

      <footer className="border-t pt-4 text-xs leading-6 text-muted-foreground">
        <p>
          <strong className="text-foreground">What this page shows:</strong> the
          stored result of one trace, exactly as it was recorded when the case
          was saved.
        </p>
        <p>
          <strong className="text-foreground">What it does not show:</strong>{" "}
          anything that would require re-querying a provider. A report re-render
          is a new rendering of this data, not a new investigation.
        </p>
      </footer>
    </div>
  );
}
