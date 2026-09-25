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
import { ArrowLeft, Download, FileText } from "lucide-react";
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
import { FundFlowGraph, NodeInspector } from "@/components/fund-flow-graph";
import { TransactionTable } from "@/components/transaction-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export default function InvestigationDetail() {
  const { id } = useParams();

  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [regenerating, setRegenerating] = useState(false);
  // The entity drawer. Node details used to sit permanently under the graph in a
  // narrow column beside it; they now open over the graph on demand, so the
  // canvas keeps the whole content width.
  const [inspected, setInspected] = useState(null);

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
      // Built from the stored result by the existing backend endpoint. It does
      // not re-trace, so the graph in the dossier is the graph on screen, and
      // `record_url` is resolved through the backend's own report route rather
      // than a path assembled here.
      const res = await api.regenerateReport(id);
      setRecord((prev) => (prev ? { ...prev, report_url: res.report_url } : prev));
      toast.success("Report exported successfully.");
      if (res.note) toast.info(res.note);
    } catch (e) {
      // The action is not disabled by a failure, so it can simply be retried.
      toast.error(e.message || "Unable to generate the PDF report. Please try again.");
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
            {/*
              One report action, not two. Previously this header only offered a
              download once a dossier already existed, and otherwise showed an
              outline "Re-render PDF" -- so for a case that had never been
              exported there was no primary way to get one, and the page ended
              with a "PDF dossier: Not available" row that read like a dead end.

              Both states now go through the same control and the same real
              backend endpoint, `POST /reports/{id}/regenerate`, which rebuilds
              the PDF from the stored result. It does not re-trace, so the
              dossier cannot describe a different moment than the page showing
              it, and it works for a partial case because the PDF renders the
              partial status rather than hiding it.
            */}
            {/*
              Two branches rather than one button with a conditional `render`
              prop. Base UI's Button treats a present-but-undefined `render` as
              "no element to render into" and renders nothing, so the one-control
              version silently disappeared whenever no report existed yet --
              exactly the case that needed it most.
            */}
            {pdf ? (
              <Button
                render={
                  <a href={pdf} target="_blank" rel="noopener noreferrer" />
                }
                title="Opens the report already stored for this investigation."
              >
                <Download data-icon="inline-start" />
                Export PDF Report
              </Button>
            ) : (
              <Button
                onClick={regenerate}
                disabled={regenerating}
                title="Builds the report from this investigation's stored result. It does not re-run the trace."
              >
                <FileText data-icon="inline-start" />
                {regenerating ? "Generating report…" : "Export PDF Report"}
              </Button>
            )}
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

      {/*
        One column, full width.
        This used to be `lg:grid-cols-[1fr_20rem]` with the graph in the `1fr`
        and a permanent "This case" aside beside it. On a normal desktop that
        left the graph -- and the 3D canvas inside it -- around 300px wide,
        which is why the 3D view read as a static object: a working
        CameraControls on a canvas that narrow has nowhere to move. The graph is
        the primary investigation surface, so it now takes the full measure and
        everything secondary sits below it or behind a disclosure.
      */}
      <div className="min-w-0 space-y-6">
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
              onSelectNode={setInspected}
            />
          </SectionCard>

          {/*
            Entity details, over the graph rather than beside it. The sheet is
            narrow by design, but it floats: the graph underneath keeps its full
            width and the selected node stays in view, so the entity is read in
            context rather than after navigating away from it.
          */}
          <Sheet
            open={Boolean(inspected)}
            onOpenChange={(open) => {
              if (!open) setInspected(null);
            }}
          >
            <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
              <SheetHeader>
                <SheetTitle>Address details</SheetTitle>
                <SheetDescription>
                  What the engine established about this address, and the evidence
                  behind each claim.
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6">
                <NodeInspector
                  node={inspected}
                  chain={result.chain}
                  onClose={() => setInspected(null)}
                />
              </div>
            </SheetContent>
          </Sheet>

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

        {/*
          Investigation metadata, folded away by default. It is genuinely
          useful for an analyst and for methodological transparency, but it is
          not what the page is for, and next to the graph it was costing the
          graph its width.
        */}
        <details className="rounded-xl border bg-card/50">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium marker:hidden">
            <span className="text-muted-foreground">
              Investigation details
            </span>{" "}
            <span className="text-xs text-muted-foreground">
              id, seed, scope, timing and provider attribution
            </span>
          </summary>
          <div className="border-t px-4 py-3">
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
              {/* Report status, phrased as state rather than as a dead end. The
                  report is produced on demand from the button at the top, so
                  "not generated yet" is a normal condition here, not a failure
                  and not the only way to get one. */}
              <ValueRow
                label="PDF report"
                reason={
                  record.report_url
                    ? null
                    : "No report has been exported for this investigation yet. Use Export PDF Report at the top of the page to build one."
                }
                copyable={Boolean(record.report_url)}
              >
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
          </div>
        </details>
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
