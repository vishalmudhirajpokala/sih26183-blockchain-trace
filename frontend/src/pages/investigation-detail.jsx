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

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, FileText } from "lucide-react";
import { toast } from "sonner";

import { api, reportHref } from "@/lib/api";
import {
  chainLabel,
  formatAmount,
  formatDateTime,
  formatDuration,
  formatCount,
  safeSourceUrl,
  statusInfo,
  truncateHash,
} from "@/lib/format";
import {
  AddressChip,
  Disclosure,
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

/**
 * The fund-flow summary: who the subject is, and where value actually moved.
 *
 * Every relationship here is read off a real normalized transaction's
 * `from_address` and `to_address`. Nothing is inferred from hop order, nothing
 * is picked because it happens to be first, and no amount is computed here --
 * `amount` is summed only from values the backend actually returned, and a
 * counterparty whose transfers carried no amount reports "Not available" rather
 * than a zero that would read as "nothing moved".
 *
 * The subject is deliberately NOT called the source. A subject is frequently the
 * *recipient*: the TRON case in the store is five inbound transfers and no
 * outbound ones, so labelling that seed "SOURCE" and its counterparties
 * "DESTINATIONS" would invert the actual direction of every transaction on the
 * page. `subject` / `from` / `to` are three different things and the copy keeps
 * them apart.
 */
function FundFlowSummary({ result, transactions, nodes, onSelectNode }) {
  const seed = result.seed || null;
  const chain = result.chain;
  const seedKey = seed ? String(seed).toLowerCase() : null;

  // A transaction-hash investigation is deterministic: the seed *is* that
  // transaction, so it has exactly one source and one destination. An address
  // investigation is not, and is aggregated instead.
  const isSingleTransfer = result.input_type === "transaction_hash";

  const flow = useMemo(() => {
    if (isSingleTransfer) {
      const tx = transactions[0] || null;
      if (!tx) {
        return { kind: "single", from: null, to: null, transaction: null };
      }
      return {
        kind: "single",
        from: tx.from_address || null,
        to: tx.to_address || null,
        transaction: tx,
      };
    }

    /*
     * Address investigation: group the seed's direct counterparties by the
     * direction the transaction actually points.
     *
     * `inbound` = the other party sent value TO the subject. Those parties are
     * senders, not destinations. `outbound` = the subject sent value to them.
     * Keyed on the lowercased address, which is the identity the engine itself
     * uses when de-duplicating nodes, so the same wallet cannot appear twice
     * under case variants.
     */
    const inbound = new Map();
    const outbound = new Map();

    for (const tx of transactions) {
      const from = tx?.from_address;
      const to = tx?.to_address;
      if (!from || !to) continue;

      const fromIsSubject = seedKey !== null && from.toLowerCase() === seedKey;
      const toIsSubject = seedKey !== null && to.toLowerCase() === seedKey;

      // Transfers between two counterparties, with the subject on neither end,
      // are not a direct relationship with the subject and are not listed here.
      if (!fromIsSubject && !toIsSubject) continue;

      const counterparty = fromIsSubject ? to : from;
      const key = counterparty.toLowerCase();
      const bucket = toIsSubject ? inbound : outbound;

      const existing = bucket.get(key);
      if (existing) {
        existing.transfers += 1;
        if (typeof tx.amount === "number") {
          // Only amounts the backend actually returned are summed. A null stays
          // null so the total can honestly report that it is unknown.
          if (existing.total === null) existing.total = null;
          else if (existing.total !== null) existing.total += tx.amount;
          if (existing.largest === null || tx.amount > existing.largest) {
            existing.largest = tx.amount;
          }
        }
        existing.assets.add(tx.asset);
        continue;
      }

      bucket.set(key, {
        address: counterparty,
        // The seed is excluded above, so a self-transfer shows up as a
        // counterparty equal to the subject -- kept, because the engine emitted
        // it and dropping it would understate the activity.
        transfers: 1,
        total: typeof tx.amount === "number" ? tx.amount : null,
        largest: typeof tx.amount === "number" ? tx.amount : null,
        assets: new Set(tx.asset ? [tx.asset] : []),
      });
    }

    return {
      kind: "multi",
      inbound: [...inbound.values()].sort((a, b) => b.transfers - a.transfers),
      outbound: [...outbound.values()].sort((a, b) => b.transfers - a.transfers),
    };
  }, [isSingleTransfer, transactions, seedKey]);

  if (isSingleTransfer) {
    const { from, to, transaction } = flow;
    if (!from && !to) return null;
    return (
      <SectionCard
        title="Transaction flow"
        description="The transfer this hash identifies. Source and destination are that transaction's own from and to."
        bodyClassName="space-y-4"
      >
        <FlowRow
          role="Source"
          address={from}
          chain={chain}
          onSelect={onSelectNode}
          nodes={nodes}
        />
        <FlowArrow
          caption={
            transaction
              ? typeof transaction.timestamp === "number"
                ? new Date(transaction.timestamp * 1000).toLocaleString()
                : "Time not available"
              : null
          }
        />
        <FlowRow
          role="Destination"
          address={to}
          chain={chain}
          onSelect={onSelectNode}
          nodes={nodes}
          detail={
            transaction
              ? `${formatAmount(transaction.amount, null, transaction.asset)} · ${truncateHash(transaction.hash, 12, 10)}`
              : null
          }
        />
      </SectionCard>
    );
  }

  const { inbound, outbound } = flow;
  const total = inbound.length + outbound.length;
  if (total === 0 && !seed) return null;

  return (
    <SectionCard
      title="Fund flow summary"
      description="The subject and the addresses value actually moved between, read from the transfers below."
      bodyClassName="space-y-4"
    >
      <FlowRow
        role="Subject"
        address={seed}
        chain={chain}
        hint="the address this investigation started from"
        onSelect={onSelectNode}
        nodes={nodes}
      />

      {total === 0 ? (
        <p className="text-sm text-muted-foreground">
          No direct transfer between the subject and another address was found in
          the transactions this run returned.
        </p>
      ) : (
        <>
          <FlowArrow
            caption={`${nodes.length} ${nodes.length === 1 ? "address" : "addresses"} · ${transactions.length} ${transactions.length === 1 ? "transfer" : "transfers"}`}
          />
          {/*
            Split by the direction the transactions point, and labelled for what
            that direction means. "Outgoing" counterparties received value from
            the subject, so they are destinations; "incoming" counterparties sent
            it, so they are senders. Collapsing both into one "destinations"
            list is the mistake this avoids.
          */}
          <div className="grid gap-4 sm:grid-cols-2">
            <CounterpartyList
              heading="Incoming"
              caption="sent value to the subject"
              items={inbound}
              chain={chain}
              onSelect={onSelectNode}
              nodes={nodes}
            />
            <CounterpartyList
              heading="Outgoing"
              caption="received value from the subject"
              items={outbound}
              chain={chain}
              onSelect={onSelectNode}
              nodes={nodes}
            />
          </div>
        </>
      )}
    </SectionCard>
  );
}

function FlowArrow({ caption }) {
  return (
    <div className="flex items-center gap-3" aria-hidden="true">
      <div className="flex flex-col items-center">
        <div className="h-4 w-px bg-border" />
        <div className="size-1.5 rotate-45 border-b border-r border-border" />
      </div>
      {caption ? <span className="text-xs text-muted-foreground">{caption}</span> : null}
    </div>
  );
}

function FlowRow({ role, address, chain, detail, hint, onSelect, nodes }) {
  const inGraph = nodes.some(
    (n) => n?.address && address && n.address.toLowerCase() === address.toLowerCase(),
  );
  return (
    <div>
      <p className="text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {role}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
        <AddressChip value={address} chain={chain} />
        {detail ? <span className="text-sm">{detail}</span> : null}
        {inGraph && onSelect ? (
          <Button
            size="xs"
            variant="ghost"
            onClick={() => onSelect(nodes.find((n) => n.address.toLowerCase() === address.toLowerCase()))}
            title="Opens this address in the graph below"
          >
            Show in graph
          </Button>
        ) : null}
      </div>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function CounterpartyList({ heading, caption, items, chain, onSelect, nodes }) {
  return (
    <div>
      <p className="text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {heading}{" "}
        <span className="font-normal normal-case tracking-normal text-xs">
          — {caption}
        </span>
      </p>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">
          None recorded
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((item) => (
            <li
              // Business identity is the address itself, never the array index:
              // a `key` of index would remount the row when the list re-sorts.
              key={item.address.toLowerCase()}
              className="rounded-md border bg-card px-2.5 py-2"
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <AddressChip value={item.address} chain={chain} />
                {onSelect &&
                nodes.some(
                  (n) =>
                    n?.address &&
                    n.address.toLowerCase() === item.address.toLowerCase(),
                ) ? (
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() =>
                      onSelect(
                        nodes.find(
                          (n) =>
                            n.address.toLowerCase() ===
                            item.address.toLowerCase(),
                        ),
                      )
                    }
                    title="Opens this address in the graph below"
                  >
                    Show in graph
                  </Button>
                ) : null}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {item.transfers}{" "}
                {item.transfers === 1 ? "transfer" : "transfers"}
                {" · "}
                {item.total === null
                  ? "amount not available"
                  : `${formatAmount(item.total, null, [...item.assets].join("/") || null)} total`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
      /*
       * The backend's failure detail is deliberately not surfaced. It is an
       * implementation string -- an exception class name, a renderer message --
       * and it tells an investigator nothing they can act on, while telling
       * them a great deal about how the software is built. The full error is
       * logged for a developer; the user gets a clean sentence and a button
       * that is still enabled, because a failure must be retryable.
       */
      console.error("Report export failed for investigation", id, e);
      toast.error("Unable to generate the PDF report. Please try again.");
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

  /*
   * Status vocabulary.
   *
   * The raw backend value is never rendered. `partial` is a perfectly good
   * enum but "PARTIAL" in the page header reads as a broken investigation, and
   * `provider_error` reads as a BlockTrace bug rather than an unreachable
   * provider. `statusInfo` maps the real enum onto investigator language, and
   * anything it does not recognise falls through to its own neutral label
   * rather than to a guess.
   */
  const status = statusInfo(result.status);

  /*
   * Limited scope is shown when the engine itself recorded truncation, not when
   * the status string happens to be `partial`. Those are different facts: an
   * adapter can return `partial` with `truncated: false` when a hop genuinely
   * had no data, and claiming a boundary was hit when none was would be the
   * mirror image of the over-warning this is replacing.
   */
  const limitedScope = Boolean(metadata.truncated);
  const boundaryReasons = Array.isArray(metadata.truncation_reasons)
    ? metadata.truncation_reasons
    : [];

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
            /*
              Status and chain as two compact badges. The engine's
              `status_detail` sentence used to sit here as well, but it restated
              the scope note immediately below in plainer words -- two paragraphs
              saying one thing. It stays on the record, rendered in full under
              Investigation details.
            */
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={status.tone === "negative" ? "destructive" : "secondary"}>
                {status.short}
              </Badge>
              <Badge variant="outline">
                {result.chain_name || chainLabel(result.chain) || result.chain}
              </Badge>
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

      {/*
        A case that was cut short says so -- quietly.

        This used to be an amber block above the fold carrying a "PARTIAL" badge,
        a "Boundary: max depth 1" line, a paragraph about absence not being
        evidence, and a "Why the trace stopped" list. Four separate statements
        that the trace reached a configured boundary, in the position of highest
        emphasis on the page.

        The boundary is real and hiding it would be dishonest, so it is still
        stated. It is now one line of plain text under the status badge, and the
        engine's own reasons are one keystroke away. Nothing here is a failure:
        a run that explored 48 addresses before hitting the node ceiling produced
        a substantial result, and the page should read that way.
      */}
      {limitedScope ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Limited scope</span>
          <span>
            Results reflect the addresses examined in this run. Activity may
            continue beyond them.
          </span>
        </div>
      ) : null}

      {/*
        The four numbers that answer "what happened" without reading anything.
        Every value here is the stored count or the engine's own score -- the
        React side labels and formats, it does not derive.
      */}
      <StatGrid
        items={[
          {
            label: "Risk",
            value: <RiskBadge level={risk.risk_level} score={risk.risk_score} />,
            tooltip: "The risk engine's score and level for this trace.",
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
        which is why the 3D view read as a static object. The graph is the
        primary investigation surface, so it now takes the full measure and
        everything secondary sits below it or behind a disclosure.
      */}
      <div className="min-w-0 space-y-6">
        <div className="min-w-0 space-y-6">
          {/*
            The flow summary is the first section of the investigation, before
            the risk panel and before the graph.

            The order it establishes is the order the questions arrive in: who
            is the subject and where did the value move, then why is that risky,
            then show me the shape, then show me the rows. The risk panel's
            engine summary, the score derivation and the methodology all read as
            *why the software says* something, and putting them first made an
            investigator page through the analysis to find out where the money
            went.
          */}
          <FundFlowSummary
            result={result}
            transactions={transactions}
            nodes={nodes}
            onSelectNode={setInspected}
          />

          {/*
            `RiskPanel` renders its own `SectionCard`, so it is mounted directly.
            Wrapping it in a second card titled "Risk assessment" -- which is what
            this did -- produced two consecutive headings reading "Risk
            assessment" with the panel's own description between them, and two
            nested borders around one body.
          */}
          <RiskPanel risk={risk} />

          <SectionCard
            title="Fund flow"
            description="Value movement between addresses, laid out by hop distance from the subject."
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
            description={
              transactions.length === 1
                ? "1 normalized transfer, not only those in the graph."
                : `${transactions.length} normalized transfers, not only those in the graph.`
            }
          >
            <TransactionTable
              transactions={transactions}
              chain={result.chain}
              seed={result.seed}
            />
          </SectionCard>
        </div>

        {/*
          Investigation metadata, folded away.

          It is genuinely useful for an analyst and for methodological
          transparency, but it is not what the page is for, so it is below the
          ledger rather than beside the graph. The full seed lives here in full
          and stays copyable, because the title only shows enough of it to
          identify the case.
        */}
        <Disclosure
          label="Investigation details"
          hint="id, seed, scope and timing"
          bodyClassName="text-sm"
        >
          <dl className="divide-y">
            <ValueRow label="Investigation id" mono copyable>
              {record.id}
            </ValueRow>
            <ValueRow label="Seed" mono copyable>
              {result.seed}
            </ValueRow>
            <ValueRow label="Input type">{result.input_type}</ValueRow>
            <ValueRow label="Status">{result.status}</ValueRow>
            {result.status_detail ? (
              <ValueRow label="Status detail">{result.status_detail}</ValueRow>
            ) : null}
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
                report is produced on demand from the button at the top, so "not
                generated yet" is a normal condition here, not a failure and not
                the only way to get one. */}
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

          {result.entity ? (
            <div className="mt-4 border-t pt-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Strongest attribution
              </h3>
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                The best-sourced label found anywhere in this trace.
              </p>
              <dl className="mt-1 divide-y">
                <ValueRow label="Entity">{result.entity.name}</ValueRow>
                <ValueRow label="Type">{result.entity.type}</ValueRow>
                <ValueRow label="Source type">
                  {result.entity.source_type}
                </ValueRow>
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
              </dl>
            </div>
          ) : null}
        </Disclosure>

        {/*
          Implementation-level transparency: which providers answered, how they
          behaved, and the engine's own run notes.

          All of it is factual and worth keeping -- a trace that succeeded after
          one provider failed should show both facts, and a note explaining why a
          boundary was hit is the difference between "we looked" and "we stopped
          looking". But cache hit rates and HTTP status codes describe the
          plumbing, not the case, so it sits last, behind a toggle. `EvidenceNotes`
          strips Python exception class names out of these strings; see
          `humaniseNote`.
        */}
        <Disclosure
          label="Technical details"
          hint="investigation scope, providers consulted and engine run notes"
          bodyClassName="text-xs"
        >
          {/*
            Why the scope was limited. The engine names the exact boundary and,
            for a depth limit, the address that hit it. That is implementation
            vocabulary, so it lives here rather than in the header -- but it is
            the evidence behind the "Limited scope" line above, and it is not
            removed.
          */}
          {limitedScope ? (
            <div className="mb-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Why the scope was limited
              </h3>
              {boundaryReasons.length ? (
                <ul className="mt-1.5 space-y-1 text-[11px] leading-4 text-muted-foreground">
                  {boundaryReasons.map((reason, i) => (
                    <li key={i} className="font-mono break-words">
                      {reason}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
                  The engine recorded truncation without naming a boundary.
                </p>
              )}
              <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
                Configured for this run: max depth{" "}
                {typeof metadata.depth_limit === "number"
                  ? metadata.depth_limit
                  : null}
                , max addresses{" "}
                {typeof metadata.node_limit === "number"
                  ? metadata.node_limit
                  : null}
                . Reached depth {metadata.max_depth_reached}, examined{" "}
                {formatCount(metadata.nodes_examined)}.
              </p>
            </div>
          ) : null}

          <ProviderLedger usage={metadata.provider_usage} />
          <div className="mt-3">
            <EvidenceNotes notes={notes} />
          </div>
          <p className="mt-3 border-t pt-3 text-[10px] leading-4 text-muted-foreground">
            <strong className="text-foreground">What this page shows:</strong> the
            stored result of one trace, exactly as it was recorded when the case
            was saved.{" "}
            <strong className="text-foreground">What it does not show:</strong>{" "}
            anything that would require re-querying a provider. Exporting the
            report is a new rendering of this data, not a new investigation.
          </p>
        </Disclosure>
      </div>
    </div>
  );
}
