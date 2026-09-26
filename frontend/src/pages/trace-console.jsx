/**
 * Trace Console — the primary working surface.
 *
 * The flow is: type → detect → confirm chain → run → read. Each step is
 * separate because each answers a different question, and merging them is what
 * makes tools like this dangerous: an investigator who does not see that an
 * input was *ambiguous* between three EVM chains will end up with a confident,
 * wrong, richly-detailed finding.
 *
 * The two behaviours that matter most here:
 *
 * 1. **Detection is debounced and cancellable.** A superseded in-flight request
 *    is aborted, so a slow response for a half-typed address can never
 *    overwrite the result for a complete one.
 * 2. **An ambiguous input is a stop, not a suggestion.** A `0x…` address is
 *    valid on Ethereum, BSC and Polygon simultaneously. The console does not
 *    pick one. It makes the operator choose, because the same address on
 *    three chains is three different investigations with three different
 *    answers.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  AlertTriangleIcon,
  CircleCheckIcon,
  Loader2Icon,
  PlayIcon,
  RotateCcwIcon,
  InfoIcon,
} from "lucide-react";

import {
  Disclosure,
  EmptyState,
  ErrorPanel,
  EvidenceNotes,
  LoadingBlock,
  PageHeader,
  ProviderLedger,
  RiskBadge,
  SectionCard,
  ValueRow,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FundFlowGraph } from "@/components/fund-flow-graph";
import { TransactionTable } from "@/components/transaction-table";
import { RiskPanel } from "@/components/risk-panel";
import { api, reportHref } from "@/lib/api";
import { EXAMPLE_TRACES, shortAddress } from "@/lib/example-traces";
import { CHAIN_ORDER, chainLabel, statusInfo } from "@/lib/format";

/** How long to wait after the last keystroke before asking the detector. */
const DETECT_DEBOUNCE_MS = 320;

/**
 * Investigation budget overrides.
 *
 * Intentionally empty. `POST /trace/run` takes `max_depth`, `max_nodes`,
 * `max_txs_per_node` and `deadline_seconds` as *optional* fields, and the
 * orchestrator substitutes the engine's own values whenever they are absent:
 *
 *   depth    = MAX_TRACE_DEPTH      if max_depth       is None else ...
 *   node_cap = MAX_TRACE_NODES      if max_nodes       is None else ...
 *   tx_cap   = MAX_TXS_PER_NODE     if max_txs_per_node is None else ...
 *   deadline = TRACE_DEADLINE_SECONDS if deadline_seconds is None else ...
 *
 * This used to seed `{depth: 2, nodes: 25, txs: 10, deadline: 90}`, which
 * meant every ordinary trace overrode the engine. That was not cosmetic: the
 * `10` doubled the per-address history the backend had deliberately capped at
 * `5`, and was enough to push a routine wallet trace past its time budget and
 * return `504`. Leaving these blank means BlockTrace picks, the user does not.
 *
 * A field is only added to the request body once someone types into it under
 * Advanced options, so an override is always deliberate and never accidental.
 */
const DEFAULTS = {};

/**
 * The detection result, rendered as a statement about the input.
 *
 * It never says "looks like" for a chain it inferred silently, and it never
 * lists a chain as a candidate the detector did not actually return.
 */
function DetectionCard({ detection, checking, onPickChain }) {
  if (checking) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
        <Loader2Icon className="size-3.5 animate-spin" aria-hidden="true" />
        Checking the format…
      </div>
    );
  }

  if (!detection) {
    return (
      <p className="text-xs text-muted-foreground">
        Enter an address or a transaction hash and BlockTrace will identify the
        chain before spending any provider calls.
      </p>
    );
  }

  const { valid, ambiguous, chain, chain_name, input_type, address_type, reason, note, network } = detection;
  // The engine returns the chains the input is structurally valid on. Only
  // those are offered — the chain dropdown is never padded with chains the
  // detector did not name, because offering a chain the input is *not* valid
  // on invites a run that can only fail.
  const candidates = (detection.candidates || []).filter((c) => CHAIN_ORDER.includes(c));

  if (!valid) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs dark:border-red-900 dark:bg-red-950/40">
        <div className="flex items-center gap-2 font-semibold text-red-800 dark:text-red-200">
          <AlertTriangleIcon className="size-3.5" />
          Not a recognised address or transaction hash
        </div>
        {reason ? <p className="mt-1.5 text-red-700 dark:text-red-300">{reason}</p> : null}
      </div>
    );
  }

  return (
    <div
      className={`rounded-md border px-3 py-2.5 text-xs ${
        ambiguous
          ? "border-sky-200 bg-sky-50 dark:border-sky-900 dark:bg-sky-950/40"
          : "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {ambiguous ? (
          <InfoIcon className="size-3.5 text-sky-700 dark:text-sky-300" />
        ) : (
          <CircleCheckIcon className="size-3.5 text-emerald-700 dark:text-emerald-300" />
        )}
        <span
          className={`font-semibold ${
            ambiguous
              ? "text-sky-900 dark:text-sky-200"
              : "text-emerald-900 dark:text-emerald-200"
          }`}
        >
          {ambiguous
            ? "EVM address — network not yet known"
            : `Detected on ${chain_name || chainLabel(chain)}`}
        </span>
        {input_type ? (
          <span className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground dark:bg-black/20">
            {input_type.replace("_", " ")}
          </span>
        ) : null}
        {address_type ? (
          <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] text-muted-foreground dark:bg-black/20">
            {address_type}
          </span>
        ) : null}
        {network ? (
          <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] text-muted-foreground dark:bg-black/20">
            {network}
          </span>
        ) : null}
        {typeof detection.confidence === "number" && !ambiguous ? (
          <span className="ml-auto text-[10px] text-muted-foreground">
            format confidence {detection.confidence}%
          </span>
        ) : null}
      </div>

      {/*
        An EVM address is twenty bytes of hex and is therefore valid on
        Ethereum, BSC and Polygon simultaneously, so the *format* genuinely
        cannot name the network. That used to be a blocking amber warning that
        made the user pick.

        It is now a neutral note, because the format is only half the answer:
        when the trace starts, BlockTrace asks each candidate network's own
        indexer whether it has ever seen the address and follows the evidence.
        One network with activity is chosen automatically and this note
        disappears. Several is reported back as a short result chooser after
        detection, which is a different question from "which network is this
        valid on".
      */}
      {ambiguous ? (
        <p className="mt-2 text-sky-800 dark:text-sky-200">
          BlockTrace will work out which network this belongs to by checking
          each one for activity when you trace it.
        </p>
      ) : null}

      {note ? <p className="mt-1.5 text-muted-foreground">{note}</p> : null}
    </div>
  );
}

/**
 * The investigation budget, collapsed by default and never required.
 *
 * A blank field means "BlockTrace decides", and the hint beside it states the
 * value the engine will actually use, read from `/health` rather than guessed
 * here. These exist for an investigator who needs a wider or tighter run than
 * the default; nobody should have to open them to trace a wallet.
 */
function AdvancedOptions({ options, setOptions, disabled, recommended, chain, setChain }) {
  const fields = [
    {
      key: "max_depth",
      label: "Investigation distance",
      min: 0,
      max: 6,
      hint: "How many transfers away from the starting address to follow.",
    },
    {
      key: "max_nodes",
      label: "Maximum addresses to investigate",
      min: 1,
      max: 200,
      hint: "A ceiling on how many addresses end up in the graph.",
    },
    {
      key: "max_txs_per_node",
      label: "Transaction history per address",
      min: 1,
      max: 50,
      hint: "How much history to pull for each address.",
    },
    {
      key: "deadline_seconds",
      label: "Maximum investigation time (seconds)",
      min: 5,
      max: 300,
      hint: "The longest BlockTrace will spend on this investigation.",
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label htmlFor="chain" className="text-xs">
          Network override
        </Label>
        {/* `null` is Base UI's "no value chosen" state. An empty string would
            be a value no item has, which renders as a selection that does not
            exist. Leaving it unset is the normal path: the backend resolves the
            network from provider evidence. */}
        <Select value={chain || null} onValueChange={(v) => setChain(v ?? "")}>
          <SelectTrigger id="chain" className="w-full">
            <SelectValue placeholder="Detect automatically" />
          </SelectTrigger>
          <SelectContent>
            {CHAIN_ORDER.map((c) => (
              <SelectItem key={c} value={c}>
                {chainLabel(c)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[10px] leading-4 text-muted-foreground">
          Normally BlockTrace works this out from which network has activity.
          Pin it only to force a specific network.
        </p>
      </div>
      {fields.map((f) => {
        const suggested = recommended?.[f.key];
        return (
          <div key={f.key} className="space-y-1.5">
            <Label htmlFor={f.key} className="text-xs">
              {f.label}
            </Label>
            <Input
              id={f.key}
              type="number"
              min={f.min}
              max={f.max}
              disabled={disabled}
              placeholder={suggested !== undefined ? String(suggested) : "Automatic"}
              value={options[f.key] ?? ""}
              onChange={(e) =>
                setOptions((prev) => ({ ...prev, [f.key]: e.target.value }))
              }
            />
            <p className="text-[10px] leading-4 text-muted-foreground">
              {f.hint}{" "}
              {suggested !== undefined ? (
                <span className="opacity-80">
                  Leave blank to use {suggested}
                  {f.key === "deadline_seconds" ? " seconds" : ""}.
                </span>
              ) : null}
            </p>
          </div>
        );
      })}
    </div>
  );
}

/** The finished result, rendered in the order an investigator reads it. */
/**
 * The addresses a trace actually reached, as a list.
 *
 * The graph shows the shape of the flow; this shows the inventory. Both are
 * views of the same nodes and neither replaces the other, so it lives behind a
 * disclosure rather than on the first screen: a reader looking for "which
 * addresses did this touch" wants a list, and a reader looking for "how did the
 * money move" wants the picture, and only one of them is the question they
 * arrived with.
 *
 * Attribution is shown per address rather than only for the trace overall,
 * because "which of these are labelled" is the question the whole product
 * exists to answer, and it is answerable per address.
 */
function AddressTable({ nodes }) {
  if (!nodes.length) {
    return (
      <p className="px-4 py-3 text-xs text-muted-foreground">
        No addresses were returned for this run.
      </p>
    );
  }

  const ordered = [...nodes].sort((a, b) => {
    if (a.is_seed !== b.is_seed) return a.is_seed ? -1 : 1;
    const da = typeof a.depth === "number" ? a.depth : 99;
    const db = typeof b.depth === "number" ? b.depth : 99;
    if (da !== db) return da - db;
    return String(a.address || "").localeCompare(String(b.address || ""));
  });

  return (
    <ul className="divide-y">
      {ordered.map((node) => (
        <li
          key={node.address}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-xs"
        >
          <span className="font-mono break-all">{node.address}</span>
          {node.is_seed ? (
            <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground">
              Traced
            </span>
          ) : null}
          {typeof node.depth === "number" ? (
            <span className="shrink-0 text-muted-foreground">hop {node.depth}</span>
          ) : null}
          {node.entity ? (
            <span className="shrink-0 text-muted-foreground">
              {node.entity.name} · {String(node.entity.type || "").replace(/_/g, " ")} ·{" "}
              {node.confidence}% · {String(node.source_type || "").replace(/_/g, " ")}
            </span>
          ) : (
            <span className="shrink-0 text-muted-foreground">no attribution</span>
          )}
          <span className="shrink-0 text-muted-foreground">
            in {node.inbound ?? 0} / out {node.outbound ?? 0}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * A one-line, plain-English description of what this run actually covered.
 *
 * Generated from the recorded values rather than templated per case, so it
 * cannot claim more reach than the run had. The clause after the dash is a
 * pointer rather than a summary: the reader is being told that the limits are
 * documented below, which is the honest thing to do when the answer is
 * "some of it".
 */
function coverageLine(result, meta) {
  const hops = typeof meta.max_depth_reached === "number" ? meta.max_depth_reached : null;
  const addresses = typeof meta.nodes_examined === "number" ? meta.nodes_examined : null;
  const transfers =
    typeof meta.transactions_inspected === "number" ? meta.transactions_inspected : null;

  const bits = [];
  if (hops !== null) bits.push(`${hops} hop${hops === 1 ? "" : "s"}`);
  if (addresses !== null) bits.push(`${addresses} address${addresses === 1 ? "" : "es"}`);
  if (transfers !== null) bits.push(`${transfers} transfer${transfers === 1 ? "" : "s"}`);

  const covered = bits.length ? bits.join(", ") : "no addresses";
  const limited = meta.truncated ? "Trace limited to" : "Trace covered";
  return meta.truncated
    ? `${limited} ${covered} — see below for what was and wasn't examined`
    : `${limited} ${covered}`;
}

function ResultPanel({ response, onReset }) {
  const navigate = useNavigate();
  const result = response.result || {};
  const meta = result.metadata || {};
  const risk = result.risk || {};
  const status = statusInfo(result.status);
  const href = reportHref(response.report_url || result.report);

  const nodeCount = (result.nodes || []).length;
  const transferCount = (result.transactions || []).length;
  const durationMs = meta.duration_ms;

  // The entity is the best attribution found anywhere in the trace, which is
  // usually a counterparty rather than the subject. Labelling it "destination"
  // would be a stronger claim than the data supports, so the hero says what it
  // actually is and the report's fuller treatment lives in the PDF.
  const entity = result.entity || null;
  const entityLabel = entity
    ? `${entity.name} — ${String(entity.type || "").replace(/_/g, " ")}`
    : "No entity identified";

  const contractNote = (result.evidence_notes || []).find(
    (n) => typeof n === "string" && n.includes("token contract"),
  );
  const otherNotes = (result.evidence_notes || []).filter((n) => n !== contractNote);

  // Provider calls, summarised. The full per-call log is one keystroke away, but
  // a reader's first question is whether anything failed, and that is answered
  // by a count rather than by scrolling sixty-five rows of "HTTP 200".
  const usage = meta.provider_usage || [];
  const failed = usage.filter((p) => !p.ok);
  const latencies = usage
    .map((p) => p.latency_ms)
    .filter((v) => typeof v === "number" && Number.isFinite(v));
  const avgLatency = latencies.length
    ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
    : null;
  const providerSummary = !usage.length
    ? "No provider calls were made"
    : failed.length
      ? `${usage.length} provider calls, ${failed.length} failed`
      : `${usage.length} provider calls, all succeeded${
          avgLatency !== null ? `, avg ${avgLatency}ms` : ""
        }`;

  return (
    <div className="space-y-6">
      {/*
        The hero: the four things a reader came for, in the order they ask for
        them. What was traced, who it turned out to involve, how risky, and how
        far the run actually got.

        The risk level appears here and nowhere else on this page. It used to be
        repeated by the outcome block, the risk panel badge, the score bar and
        the indicators header, which is four statements of one conclusion and a
        strong hint that none of them was the real one.
      */}
      <SectionCard
        bodyClassName="space-y-4"
        action={
          <Button size="sm" variant="outline" onClick={onReset}>
            <RotateCcwIcon />
            New trace
          </Button>
        }
      >
        <div className="space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Subject wallet
          </p>
          <p className="font-mono text-sm break-all">{result.seed}</p>
        </div>

        <div className="space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Entity identified
          </p>
          <p className="text-sm">
            {entity ? (
              <>
                <span className="font-medium">{entity.name}</span>
                <span className="text-muted-foreground">
                  {" "}
                  — {String(entity.type || "").replace(/_/g, " ")},{" "}
                  {entity.confidence}% confidence,{" "}
                  {String(entity.verification_status || "").replace(/_/g, " ")}
                </span>
              </>
            ) : (
              <span className="text-muted-foreground">{entityLabel}</span>
            )}
          </p>
          {entity ? (
            <p className="text-[10px] leading-4 text-muted-foreground">
              Best attribution found anywhere in this trace, not necessarily the
              traced address itself.
            </p>
          ) : null}
        </div>

        <div className="space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Risk
          </p>
          <RiskBadge
            level={risk.risk_level}
            score={typeof risk.risk_score === "number" ? risk.risk_score : null}
          />
        </div>

        <div className="space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Coverage
          </p>
          <p className="text-sm text-muted-foreground">
            {coverageLine(result, meta)}
          </p>
          {result.status_detail ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {result.status_detail}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {response.investigation_id ? (
            <Button
              size="sm"
              onClick={() => navigate(`/app/investigations/${response.investigation_id}`)}
            >
              Open investigation
            </Button>
          ) : null}
          {href ? (
            <Button
              size="sm"
              variant="outline"
              render={<a href={href} target="_blank" rel="noreferrer noopener" />}
            >
              Open PDF report
            </Button>
          ) : null}
          {!response.investigation_id ? (
            <span className="text-xs text-muted-foreground">
              This run was not saved to history.
            </span>
          ) : null}
          <span className="text-[10px] text-muted-foreground">
            {result.chain_name || chainLabel(result.chain)} ·{" "}
            {status.short}
            {typeof durationMs === "number" ? ` · ${durationMs} ms` : ""}
          </span>
        </div>

        {/*
          The contract-vs-wallet explanation sits directly under the hero, where
          it changes how the score above should be read. It used to sit after the
          stats row inside the outcome block, which put a paragraph of caveat
          between the reader and the number it qualifies.
        */}
        {contractNote ? (
          <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            {contractNote}
          </p>
        ) : null}
        {otherNotes.length ? <EvidenceNotes notes={otherNotes} /> : null}
      </SectionCard>

      {/* compact: the hero above owns the level and score. */}
      <RiskPanel risk={risk} chain={result.chain} compact />

      <SectionCard
        title="Fund flow"
        description={
          meta.truncated
            ? "This graph was truncated by the run's limits — what is shown is the part that was established."
            : "Every address and transfer the providers actually returned for this run."
        }
      >
        <FundFlowGraph
          nodes={result.nodes || []}
          edges={result.edges || []}
          transactions={result.transactions || []}
          chain={result.chain}
          seed={result.seed}
        />
      </SectionCard>

      {/*
        The three tables below are complete, not samples, and none of them is
        truncated to make the page shorter -- they are collapsed so the first
        screen is the finding. Each states its own size in the collapsed header,
        so a reader knows what they are not looking at before deciding to look.
      */}
      <Disclosure
        label="Transaction ledger"
        hint={
          transferCount
            ? `${transferCount} transfer${transferCount === 1 ? "" : "s"} found`
            : "no transfers retrieved"
        }
        bodyClassName="p-0"
      >
        <TransactionTable
          transactions={result.transactions || []}
          chain={result.chain}
          seed={result.seed}
        />
      </Disclosure>

      <Disclosure
        label="Addresses examined"
        hint={
          nodeCount
            ? `${nodeCount} address${nodeCount === 1 ? "" : "es"} in the graph`
            : "no addresses retrieved"
        }
        bodyClassName="p-0"
      >
        <AddressTable nodes={result.nodes || []} />
      </Disclosure>

      <Disclosure label="Provider activity" hint={providerSummary} bodyClassName="pt-2">
        <ProviderLedger usage={usage} />
      </Disclosure>

      <SectionCard title="Provenance and method" bodyClassName="space-y-1 pt-2">
        <ValueRow label="Investigation id" mono copyable>
          {meta.investigation_id || response.investigation_id}
        </ValueRow>
        <ValueRow label="Seed input" mono copyable>
          {result.seed}
        </ValueRow>
        <ValueRow label="Max depth reached">
          {typeof meta.max_depth_reached === "number" ? meta.max_depth_reached : null}
        </ValueRow>
        <ValueRow label="Depth limit">
          {typeof meta.depth_limit === "number" ? meta.depth_limit : null}
        </ValueRow>
        <ValueRow label="Addresses examined">
          {typeof meta.nodes_examined === "number" ? meta.nodes_examined : null}
        </ValueRow>
        <ValueRow label="Transfers inspected">
          {typeof meta.transactions_inspected === "number"
            ? meta.transactions_inspected
            : null}
        </ValueRow>
        <ValueRow label="Truncated">
          {meta.truncated === undefined ? null : meta.truncated ? "Yes" : "No"}
        </ValueRow>
        {meta.subject_is_contract !== undefined ? (
          <ValueRow label="Subject is a contract">
            {meta.subject_is_contract === null
              ? "Could not be determined"
              : meta.subject_is_contract
                ? "Yes"
                : "No"}
          </ValueRow>
        ) : null}
        {/*
          Chain-agnostic, and it has to be. This line used to say "TRON amounts
          arrive already divided out of SUN by the adapter" unconditionally, so an
          Ethereum trace explained TRON's unit convention to a reader looking at
          an ERC-20 amount. The division is real on every chain; only the unit
          named was chain-specific.
        */}
        <p className="pt-2 text-[10px] leading-4 text-muted-foreground">
          Amounts are shown in each asset's own units, already converted by the
          adapter from the raw on-chain integer using that token contract's
          decimals. No conversion happens in the browser.
        </p>
      </SectionCard>
    </div>
  );
}

export default function TraceConsole() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [query, setQuery] = useState(() => searchParams.get("query") || "");
  const [chain, setChain] = useState(() => searchParams.get("chain") || "");
  const [options, setOptions] = useState(DEFAULTS);
  const [title, setTitle] = useState("");
  const [save, setSave] = useState(true);
  const [generateReport, setGenerateReport] = useState(true);

  const [detection, setDetection] = useState(null);
  const [checking, setChecking] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [response, setResponse] = useState(null);
  const [recommended, setRecommended] = useState(null);
  const [multiChain, setMultiChain] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // A ref, not state: the abort controller must be readable from the cleanup of
  // the effect that created it without re-triggering that effect.
  const detectAbort = useRef(null);

  // -- detection ---------------------------------------------------------
  const runDetect = useCallback(
    async (text, preferred) => {
      detectAbort.current?.abort();
      if (!text || text.trim().length < 4) {
        setDetection(null);
        setChecking(false);
        return;
      }

      const controller = new AbortController();
      detectAbort.current = controller;
      setChecking(true);
      try {
        const found = await api.detect(text.trim(), preferred || null, controller.signal);
        if (!controller.signal.aborted) setDetection(found);
      } catch (err) {
        // An aborted request is a superseded one, not a failure. Reporting it
        // would flash an error on every keystroke that outran the last.
        if (err?.kind !== "timeout" && !controller.signal.aborted) {
          setDetection(null);
        }
      } finally {
        if (!controller.signal.aborted) setChecking(false);
      }
    },
    [],
  );

  useEffect(() => {
    const timer = setTimeout(() => runDetect(query, chain), DETECT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, chain, runDetect]);

  useEffect(() => () => detectAbort.current?.abort(), []);

  /*
   * The investigation budget the engine will use, read from the API rather
   * than repeated here.
   *
   * This exists only so Advanced options can say "leave blank to use 3" instead
   * of asking someone to guess. A failure is not worth an error state: the
   * panel then simply falls back to "Automatic" and the trace still runs on the
   * backend's own defaults, which is the behaviour that matters.
   */
  useEffect(() => {
    let live = true;
    api
      .health()
      .then((health) => {
        if (live && health?.config?.trace_defaults) {
          setRecommended(health.config.trace_defaults);
        }
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  // Keep the URL in step with the input, so a trace is linkable before it has
  // been run and a refresh does not silently clear the console.
  useEffect(() => {
    const next = {};
    if (query.trim()) next.query = query.trim();
    if (chain) next.chain = chain;
    setSearchParams(next, { replace: true });
  }, [query, chain, setSearchParams]);

  // -- run ---------------------------------------------------------------
  /*
   * Chain ambiguity is no longer a reason to stop. A 0x address is valid on
   * three networks, but the backend resolves that from provider evidence when
   * the trace runs, so the console's only job here is to refuse input the
   * format detector has already rejected, and to avoid firing two overlapping
   * investigations when the user clicks twice.
   *
   * The check keys on detection.valid === false, so an in-flight or absent
   * check never blocks a valid paste.
   */
  const rejected = detection?.valid === false;
  const canRun = Boolean(query.trim().length >= 8) && !rejected && !running;

  /*
   * `preset` lets the example buttons start a trace directly.
   *
   * It has to arrive as an argument rather than being read back off `query`,
   * because `setQuery` does not take effect until the next render: a handler
   * that called `setQuery(address)` and then read `query` would post the empty
   * string. Passing the address through keeps the click and the request in the
   * same tick, while `setQuery` below still updates the field so the operator
   * can see what was traced and edit from there.
   */
  async function handleRun(event, preset) {
    event?.preventDefault();

    const target = preset?.query ?? query.trim();
    const targetChain = preset?.chain ?? chain;
    if (running) return;
    if (target.length < 8) return;

    if (preset) {
      setQuery(preset.query);
      setChain(preset.chain);
      setTitle("");
    }

    setRunning(true);
    setError(null);
    try {
      const body = {
        query: target,
        preferred_chain: targetChain || null,
        save,
        generate_report: generateReport,
      };
      if (!preset && title.trim()) body.title = title.trim();

      /*
       * Only a deliberate override is sent. A blank Advanced field is omitted
       * from the body entirely, which is what tells the backend to apply its
       * own budget rather than have the console pick one.
       */
      for (const key of ["max_depth", "max_nodes", "max_txs_per_node", "deadline_seconds"]) {
        const raw = options[key];
        if (raw === undefined || raw === null || String(raw).trim() === "") continue;
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) body[key] = parsed;
      }

      const result = await api.runTrace(body);
      setResponse(result);
      setMultiChain(null);

      const status = result.result?.status;
      if (status === "provider_error" || status === "rate_limited" || status === "timeout") {
        toast.warning("The trace ran but the providers did not answer", {
          description:
            "This is a statement about provider availability, not about the address.",
        });
      } else if (save) {
        toast.success("Investigation complete", {
          description: result.investigation_id
            ? "Saved to your investigation history."
            : "Completed. It was not saved to history.",
        });
      }
    } catch (err) {
      /*
       * `ambiguous_chain` is not a failure. The backend found real activity on
       * more than one network for an address that is valid on all of them, and
       * refused to pick one because each is a separate subject. That becomes a
       * short chooser here, offered *after* detection rather than as a warning
       * in front of it, and the evidence travels with it so the choice is
       * informed rather than a guess.
       */
      if (err?.error === "ambiguous_chain") {
        const detail = err.detection || {};
        setMultiChain({
          chains: detail.candidates_with_activity || [],
          uncertain: detail.uncertain || [],
          evidence: detail.evidence || [],
        });
        setError(null);
        setResponse(null);
        return;
      }
      setError(err);
      setResponse(null);
      toast.error("The trace did not complete", { description: err.message });
    } finally {
      setRunning(false);
    }
  }

  function handleReset() {
    setResponse(null);
    setError(null);
    setQuery("");
    setChain("");
    setTitle("");
    navigate("/app/trace", { replace: true });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Trace console"
        title="Trace a wallet or transaction"
        description="Paste an address or a transaction hash. BlockTrace works out which network it belongs to, follows the money through the providers, and records what it could and could not confirm."
      />

      {/*
        The empty state for someone who has no address to paste.

        Asking for a wallet address is a fair question to ask an investigator and
        an unusable one to ask an evaluator, because the only people who can
        answer it are people who already know what a wallet address is. So the
        console offers three real ones, verifies what each one actually returns,
        and says so in the caption.

        They fill the field and start the trace themselves rather than running
        anything on mount. A trace writes an investigation, spends real provider
        quota and takes tens of seconds, so it has to be something a person
        asked for. The click is the ask.

        Every address here is a token contract. That is a deliberate choice, not
        a shortcut -- see the reasoning in `lib/example-traces.js`.
      */}
      {!query.trim() && (
        <SectionCard
          title="No address to hand?"
          bodyClassName="space-y-3"
        >
          <p className="text-xs leading-5 text-muted-foreground">
            Start from one of these. They are real, public, permanently
            verifiable addresses, and each one demonstrates something different.
          </p>
          <ul className="grid gap-2 sm:grid-cols-3">
            {EXAMPLE_TRACES.map((example) => (
              <li key={example.address}>
                <button
                  type="button"
                  disabled={running}
                  title={`${example.address} — ${chainLabel(example.chain)}`}
                  onClick={(e) =>
                    handleRun(e, {
                      query: example.address,
                      chain: example.chain,
                    })
                  }
                  className="group flex h-full w-full flex-col gap-1.5 rounded-md border border-border bg-background p-3 text-left transition-colors hover:border-primary/60 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-foreground">
                      {example.label}
                    </span>
                    <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground">
                      {chainLabel(example.chain)}
                    </span>
                  </span>
                  <span className="font-mono text-[10px] leading-4 text-muted-foreground break-all">
                    {shortAddress(example.address)}
                  </span>
                  <span className="text-[10px] leading-4 text-muted-foreground">
                    {example.shows}
                  </span>
                  {example.caveat && (
                    <span className="mt-auto flex gap-1.5 border-t border-border pt-1.5 text-[9px] leading-3.5 text-muted-foreground/90">
                      <InfoIcon className="mt-px size-2.5 shrink-0" />
                      <span>{example.caveat}</span>
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <p className="text-[10px] leading-4 text-muted-foreground">
            These are token contracts, not personal wallets, so the high flow
            numbers and risk scores they produce are a property of the
            instrument rather than a finding about whoever issued it.
          </p>
        </SectionCard>
      )}

      <form id="trace-form" onSubmit={handleRun} className="space-y-4">
        <SectionCard bodyClassName="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="query">Address or transaction hash</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Paste an address or transaction hash — T… (34), 0x… (42), or bc1…/1… for Bitcoin"
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
              />
              <Button type="submit" disabled={!canRun} className="shrink-0 sm:w-32">
                {running ? (
                  <>
                    <Loader2Icon className="animate-spin" />
                    Tracing…
                  </>
                ) : (
                  <>
                    <PlayIcon />
                    Trace
                  </>
                )}
              </Button>
            </div>
          </div>

          <DetectionCard
            detection={detection}
            checking={checking}
            onPickChain={setChain}
          />

          {/*
            No chain selector in the normal flow. The backend decides the
            network from provider evidence, and an analyst who needs to pin one
            can still do it under Advanced options, which is where a network
            override belongs.
          */}

          {/*
            Everything below the address is an *input* option, and it collapses
            once there is a result.

            It used to sit permanently above the results, which put the case-name
            field's "e.g. Mixer follow — first hop" placeholder directly above a
            finished investigation. A placeholder in an empty input is correct
            and helpful; the same placeholder sitting next to real output reads
            as though it leaked out of the result, and it did draw exactly that
            conclusion here.

            Collapsing rather than hiding keeps the capability -- someone
            re-running the same address under a different case name can reopen
            it -- and `defaultOpen` keys off whether a trace has completed, so
            the first run shows the options and later ones do not.
          */}
          <Disclosure
            /*
             * `key` is load-bearing, not decoration.
             *
             * `Disclosure` seeds its open state from `defaultOpen` on mount and
             * never looks at it again, so a disclosure rendered before the trace
             * finished stayed open afterwards -- which is precisely the stray
             * placeholder this is meant to remove. Keying on whether a result
             * exists remounts it with the right default at the moment the trace
             * completes. The alternative was making `Disclosure` controlled,
             * which changes a shared component for one caller.
             */
            key={response ? "after-trace" : "before-trace"}
            label="Options"
            hint={
              title.trim()
                ? `case: ${title.trim()}`
                : save
                  ? "named investigations are saved to history"
                  : null
            }
            defaultOpen={!response}
            bodyClassName="space-y-4 pt-3"
          >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="title">Case name (optional)</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Mixer follow — first hop"
                maxLength={200}
              />
              <p className="text-[10px] leading-4 text-muted-foreground">
                How this investigation appears in your history.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={save}
                onChange={(e) => setSave(e.target.checked)}
                className="size-3.5 accent-[var(--primary)]"
              />
              Save to history
            </label>
            {/* The report is no longer a pre-trace requirement. It moved to the
                investigation page as a single "Export PDF Report" action, so the
                main journey is Trace -> review -> export. Generating a dossier
                before the investigation has even run meant asking the user to
                commit to a report format before there was a result to describe. */}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setShowAdvanced((v) => !v)}
              aria-expanded={showAdvanced}
            >
              {showAdvanced ? "Hide advanced options" : "Advanced options"}
            </Button>
          </div>

          {showAdvanced ? (
            <div className="rounded-md border border-dashed bg-muted/30 p-3">
              <p className="mb-3 text-xs font-medium">Investigation settings</p>

              {/*
                Kept, but as a preference rather than a step. Turning this on has
                the investigation build its dossier as soon as the trace
                finishes, which is useful for an analyst running a batch; leaving
                it off is fine, because the report can be exported from the
                investigation page at any time. The label no longer promises a
                separate artefact type.
              */}
              <label className="mb-3 flex cursor-pointer items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={generateReport}
                  onChange={(e) => setGenerateReport(e.target.checked)}
                  className="size-3.5 accent-[var(--primary)]"
                />
                Build the PDF report automatically when the trace finishes
              </label>

              <AdvancedOptions
                options={options}
                setOptions={setOptions}
                disabled={running}
                recommended={recommended}
                chain={chain}
                setChain={setChain}
              />
              <p className="mt-3 text-[10px] leading-4 text-muted-foreground">
                Leave these blank and BlockTrace picks a safe budget for you.
                Changing them widens or narrows how far the investigation goes;
                anything a limit cuts off is reported as truncated in the result,
                never quietly dropped.
              </p>
            </div>
          ) : null}
          </Disclosure>
        </SectionCard>
      </form>

      {/*
        More than one network has real activity for this address. Each is a
        separate subject, so they are offered as separate investigations rather
        than merged into one cross-chain picture that no provider supports.
        A network whose provider could not be reached is named separately: it
        is unknown, not empty, and hiding that would let an outage read as a
        clean network.
      */}
      {multiChain ? (
        <SectionCard
          title="Activity found on more than one network"
          description="This address is valid on several EVM networks and more than one of them has used it. Each network below is a separate investigation with its own transactions, entities and risk."
        >
          <div className="flex flex-wrap gap-2">
            {multiChain.chains.map((c) => (
              <Button
                key={c}
                size="sm"
                onClick={() => {
                  setChain(c);
                  setMultiChain(null);
                  // Re-run pinned to the chosen network.
                  window.requestAnimationFrame(() => {
                    const form = document.getElementById("trace-form");
                    if (form) form.requestSubmit();
                  });
                }}
              >
                Investigate {chainLabel(c)}
              </Button>
            ))}
          </div>

          {multiChain.uncertain.length > 0 ? (
            <p className="mt-3 text-xs text-muted-foreground">
              Could not check{" "}
              {multiChain.uncertain.map((c) => chainLabel(c)).join(", ")} — that
              provider did not answer. Absence of activity there is unknown, not
              confirmed.
            </p>
          ) : null}
        </SectionCard>
      ) : null}

      {error ? <ErrorPanel error={error} onRetry={handleRun} /> : null}

      {running ? (
        <LoadingBlock label="Tracing fund flow — providers are being queried" />
      ) : null}

      {response ? (
        <ResultPanel response={response} onReset={handleReset} />
      ) : !running && !error ? (
        <EmptyState
          title="No trace has been run in this session"
          description="The result of a trace appears here: the outcome, the risk assessment, the fund-flow graph, the normalized transactions and the provider log."
        />
      ) : null}
    </div>
  );
}
