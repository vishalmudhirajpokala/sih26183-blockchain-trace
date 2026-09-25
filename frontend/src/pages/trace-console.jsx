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
  EmptyState,
  ErrorPanel,
  EvidenceNotes,
  LoadingBlock,
  PageHeader,
  ProviderLedger,
  SectionCard,
  StatGrid,
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
import { CHAIN_ORDER, chainLabel, statusInfo, truncateHash } from "@/lib/format";

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
function ResultPanel({ response, onReset }) {
  const navigate = useNavigate();
  const result = response.result || {};
  const meta = result.metadata || {};
  const risk = result.risk || {};
  const status = statusInfo(result.status);
  const href = reportHref(response.report_url || result.report);

  // Derived during render rather than memoized. `result` is an object from
  // the response, so its identity is fresh on every render and a useMemo keyed
  // on it would recompute every render anyway while also re-running on every
  // unrelated change. `response.result` is set once when a trace completes and
  // is replaced whole on reset, so the primitive inputs below are what
  // actually determine the values.
  const nodeCount = (result.nodes || []).length;
  const transferCount = (result.transactions || []).length;
  const durationMs = meta.duration_ms;
  const stats = [
    { label: "Chain", value: result.chain_name || chainLabel(result.chain) },
    { label: "Addresses", value: nodeCount },
    { label: "Transfers", value: transferCount },
    {
      label: "Duration",
      value: typeof durationMs === "number" ? `${durationMs} ms` : null,
    },
  ];

  return (
    <div className="space-y-6">
      <SectionCard
        title="Outcome"
        description={status.meaning}
        action={
          <Button size="sm" variant="outline" onClick={onReset}>
            <RotateCcwIcon />
            New trace
          </Button>
        }
        bodyClassName="space-y-4"
      >
        <div
          className={`rounded-md border px-4 py-3 ${
            status.tone === "negative"
              ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40"
              : status.tone === "caution"
                ? "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40"
                : status.tone === "positive"
                  ? "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40"
                  : "border-border bg-muted/40"
          }`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-semibold">{status.short}</span>
            <span className="font-mono text-xs text-muted-foreground">
              {truncateHash(result.seed)}
            </span>
          </div>
          {result.status_detail ? (
            <p className="mt-1 text-xs text-muted-foreground">{result.status_detail}</p>
          ) : null}
        </div>

        <StatGrid items={stats} />

        <EvidenceNotes notes={result.evidence_notes} />
      </SectionCard>

      <RiskPanel risk={risk} chain={result.chain} />

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

      <SectionCard
        title="Normalized transactions"
        description="The same shape on every chain. TRON amounts arrive already divided out of SUN by the adapter, so no client-side conversion happens here."
        bodyClassName="p-0"
      >
        <TransactionTable
          transactions={result.transactions || []}
          chain={result.chain}
          seed={result.seed}
        />
      </SectionCard>

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
        <ValueRow label="Addresses examined">
          {typeof meta.nodes_examined === "number" ? meta.nodes_examined : null}
        </ValueRow>
        <ValueRow label="Truncated">
          {meta.truncated === undefined ? null : meta.truncated ? "Yes" : "No"}
        </ValueRow>
        <ProviderLedger usage={meta.provider_usage || []} className="pt-3" />
      </SectionCard>

      <div className="flex flex-wrap items-center gap-2">
        {response.investigation_id ? (
          <Button onClick={() => navigate(`/app/investigations/${response.investigation_id}`)}>
            Open investigation
          </Button>
        ) : null}
        {href ? (
          <Button variant="outline" render={<a href={href} target="_blank" rel="noreferrer noopener" />}>
            Open PDF dossier
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">
            No PDF dossier was generated for this run.
          </span>
        )}
        {!response.investigation_id ? (
          <span className="text-xs text-muted-foreground">
            This run was not saved to history.
          </span>
        ) : null}
      </div>
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

  async function handleRun(event) {
    event.preventDefault();
    if (!canRun) return;

    setRunning(true);
    setError(null);
    try {
      const body = {
        query: query.trim(),
        preferred_chain: chain || null,
        save,
        generate_report: generateReport,
      };
      if (title.trim()) body.title = title.trim();

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

      <form id="trace-form" onSubmit={handleRun} className="space-y-4">
        <SectionCard bodyClassName="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="query">Address or transaction hash</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Paste an address or a hash from any supported chain"
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
            <label className="flex cursor-pointer items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={generateReport}
                onChange={(e) => setGenerateReport(e.target.checked)}
                className="size-3.5 accent-[var(--primary)]"
              />
              Generate PDF dossier
            </label>
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
