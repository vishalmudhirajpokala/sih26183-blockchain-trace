/**
 * The public landing page.
 *
 * This page makes claims about what BlockTrace does, so it has one hard rule:
 * **every claim it makes is either read from the running API or is a statement
 * about the software, not about the world.**
 *
 * Concretely, that rules out the usual landing-page furniture:
 *
 *   - no "1.2M transactions indexed"     — there is no index
 *   - no "trusted by law enforcement"     — there is no such claim to make
 *   - no "live threat feed"              — there is no threat feed
 *   - no fabricated addresses or hashes   — RULE 3
 *
 * What it *does* say is checkable: which chains are configured, what the
 * deployment's access mode is, and how the evidence model works. The chain list
 * comes from `GET /health`, so a page that says "TRON, Ethereum, BSC, Polygon,
 * Bitcoin" is a page that just asked the server whether that is true. If the
 * server cannot be reached the page says so and stops — it does not fall back
 * to a hard-coded list, because a hard-coded list on a page whose entire job is
 * provenance is exactly the thing this project is arguing against.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { NetworkMotif } from "@/components/network-motif";
import {
  ArrowRight,
  Boxes,
  FileText,
  Fingerprint,
  GitBranch,
  Network,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NotAvailable, Value } from "@/components/common";
import { api } from "@/lib/api";
import { chainLabel, CHAIN_ORDER } from "@/lib/format";

/** What the engine does, in the order it does it. */
const PIPELINE = [
  {
    icon: Fingerprint,
    title: "Detect",
    body:
      "Before any provider is called, the input is checked against every supported address and hash format. An input that is valid on three chains at once is reported as valid on all three — BlockTrace does not pick one for you.",
  },
  {
    icon: GitBranch,
    title: "Trace",
    body:
      "A chain adapter walks transfers outward from the subject and normalizes what it finds into one transaction shape. The investigation engine above it never learns which chain it is looking at.",
  },
  {
    icon: ShieldAlert,
    title: "Assess",
    body:
      "One shared risk engine scores every chain identically. Each indicator carries its own evidence, and an indicator that cannot record why it fired is shown as unsupported rather than hidden.",
  },
  {
    icon: FileText,
    title: "Report",
    body:
      "The finding becomes a PDF dossier generated from stored data. A report is a rendering of an investigation, never a second run of it, so the two cannot disagree.",
  },
];

/** The four kinds of statement a result can contain, and what each one licenses. */
const EVIDENCE_TIERS = [
  {
    tag: "Fact",
    className: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200",
    body: "What a provider returned. A block height, a transaction, a timestamp. True as of the moment it was read, and true only of the provider that returned it.",
  },
  {
    tag: "Attribution",
    className: "border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-200",
    body: "A claim that an address belongs to a named entity. Never shown without a name, a source, a source URL, and a verification status.",
  },
  {
    tag: "Signal",
    className: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200",
    body: "A pattern the engine noticed — sequencing, clustering, an unattributed destination. A lead to check, not a conclusion.",
  },
  {
    tag: "Interpretation",
    className: "border-border bg-muted text-foreground",
    body: "An inference drawn on top of the other three. Always the weakest link, and always labelled as such rather than presented as a finding.",
  },
];

/** Access mode, phrased for someone who has not signed in yet. */
function accessCopy(health, status) {
  if (status?.mode === "demo") {
    return {
      label: "Demo mode",
      href: "/app",
      cta: "Open the console",
      detail:
        "No account is required and cases are not isolated between users. Everything you see is real; the privacy around it is not.",
    };
  }
  if (status?.mode === "live") {
    return {
      label: "Sign-in required",
      href: "/login",
      cta: "Sign in",
      detail: "Case data is isolated per account. Sign in to open your investigations.",
    };
  }
  return {
    label: "Access mode unknown",
    href: "/login",
    cta: "Check access",
    detail: health
      ? "This deployment did not report a usable access mode."
      : "The API could not be reached, so BlockTrace cannot say how this deployment is configured.",
  };
}

export default function Landing() {
  const [health, setHealth] = useState(null);
  const [status, setStatus] = useState(null);
  const [reachable, setReachable] = useState(null); // null = asking, false = no

  useEffect(() => {
    let cancelled = false;
    // Both are capability questions, neither is a data load, and neither can
    // fail into a page that pretends to know the answer.
    Promise.allSettled([api.health(), api.authStatus()]).then(([h, a]) => {
      if (cancelled) return;
      setHealth(h.status === "fulfilled" ? h.value : null);
      setStatus(a.status === "fulfilled" ? a.value : null);
      setReachable(h.status === "fulfilled");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const access = accessCopy(health, status);
  // Only the chains the server named, in the canonical display order. Anything
  // the server names that this build does not know is still listed, by its raw
  // slug, rather than quietly dropped.
  const named = Array.isArray(health?.chains) ? health.chains : [];
  const ordered = [
    ...CHAIN_ORDER.filter((c) => named.includes(c)),
    ...named.filter((c) => !CHAIN_ORDER.includes(c)),
  ];

  return (
    <div className="min-h-svh bg-background">
      {/* ---------------------------------------------------------- masthead */}
      <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-5">
          {/* The real mark, with the two files swapped by theme. See the note in
              app-sidebar.jsx: the navy ink is invisible on the dark shell, and
              filtering it would also wash out the blues. */}
          <img
            src="/brand/blocktrace-mark.png"
            alt=""
            width={22}
            height={22}
            className="size-[22px] shrink-0 dark:hidden"
          />
          <img
            src="/brand/blocktrace-mark-on-dark.png"
            alt=""
            width={22}
            height={22}
            className="hidden size-[22px] shrink-0 dark:block"
          />
          <span className="font-heading text-sm font-semibold tracking-tight">BlockTrace</span>
          <nav className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="sm" render={<a href="#how" />}>
              How it works
            </Button>
            <Button variant="ghost" size="sm" render={<a href="#evidence" />}>
              Evidence model
            </Button>
            <Button size="sm" render={<Link to={access.href} />}>
              {access.cta}
              <ArrowRight data-icon="inline-end" />
            </Button>
          </nav>
        </div>
      </header>

      {/* ------------------------------------------------------------- hero */}
      <section className="relative overflow-hidden">
        {/* A static wash, not an animation. Nothing on this page moves on its
            own; a landing page for a forensic tool that pulses suggests live
            data, and there is none here. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_-10%,var(--blue-soft),transparent_70%)]"
        />
        <div className="relative mx-auto max-w-6xl px-5 py-20 sm:py-28">
          {/* Two columns on large screens: the copy keeps the reading column and
              the motif takes the space beside it. Below `lg` the second column
              is removed rather than collapsed, so the hero stays a single
              column of text on a phone. */}
          <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,0.7fr)] lg:items-center lg:gap-12">
            <div>
              <Badge
                variant="outline"
                className="mb-6 border-border bg-card text-muted-foreground"
              >
                {health?.version ? `v${health.version}` : "Multi-chain investigation console"}
                {health?.persistence ? ` · ${health.persistence} persistence` : ""}
              </Badge>

              <h1 className="max-w-3xl font-heading text-4xl leading-[1.08] font-semibold tracking-tight text-balance sm:text-5xl">
                Trace funds across chains, and show your work.
              </h1>

              <p className="mt-5 max-w-2xl text-base leading-7 text-muted-foreground sm:text-lg">
                BlockTrace follows an address or a transaction across the chains it
                can reach, normalizes every result into one shape, and separates what
                a provider <em>said</em> from what a database <em>claims</em> from
                what an engine <em>inferred</em>. Where it could not establish
                something, it says so rather than filling the gap.
              </p>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Button size="lg" render={<Link to={access.href} />}>
                  {access.cta}
                  <ArrowRight data-icon="inline-end" />
                </Button>
                <Button size="lg" variant="outline" render={<a href="#evidence" />}>
                  Read the evidence model
                </Button>
              </div>

              <p className="mt-4 text-xs text-muted-foreground">{access.detail}</p>
            </div>

            {/* Decoration, and it says so. It carries no data -- no address, no
                amount, no label -- so it cannot be read as a finding on a page
                whose copy promises everything shown is real. */}
            <div className="relative mx-auto hidden w-full max-w-sm lg:block">
              <NetworkMotif className="aspect-[4/5] w-full" />
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- chains */}
      <section className="border-y bg-card/50">
        <div className="mx-auto max-w-6xl px-5 py-8">
          <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
            <div className="flex items-center gap-2">
              <Boxes className="size-4 text-muted-foreground" aria-hidden="true" />
              <span className="text-sm font-medium">Chains configured</span>
            </div>

            {reachable === null ? (
              <span className="text-sm text-muted-foreground">Asking the API…</span>
            ) : ordered.length > 0 ? (
              <ul className="flex flex-wrap gap-2">
                {ordered.map((slug) => (
                  <li key={slug}>
                    <Badge variant="secondary">{chainLabel(slug)}</Badge>
                  </li>
                ))}
              </ul>
            ) : (
              // The list is not hard-coded, so an unreachable or
              // misconfigured API produces an honest gap rather than a
              // reassuring one.
              <NotAvailable reason="The API did not report which chains this deployment can reach." />
            )}

            <p className="ml-auto max-w-md text-xs leading-5 text-muted-foreground">
              Read from <span className="font-mono">GET /health</span> just now.
              {reachable === false
                ? " That request failed, so nothing is listed."
                : " A chain appearing here means an adapter exists — not that every provider for it is currently responding."}
            </p>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ how it works */}
      <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-16">
        <h2 className="font-heading text-2xl font-semibold tracking-tight">
          One engine, above the adapters
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          A TRON transfer arrives in SUN. A Bitcoin transfer arrives in satoshis.
          An EVM transfer may arrive with eighteen decimal places of a token
          nobody has heard of. The normalization layer divides all three before
          the result leaves the backend, so nothing downstream — not the table,
          not the graph, not the report — has a per-chain branch. That is what
          makes a new chain an adapter rather than a rewrite.
        </p>

        <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PIPELINE.map((step, i) => {
            const Icon = step.icon;
            return (
              <li key={step.title}>
                <Card size="sm" className="h-full">
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted-foreground">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <Icon className="size-4 text-primary" aria-hidden="true" />
                      <CardTitle>{step.title}</CardTitle>
                    </div>
                    <CardDescription className="leading-5">{step.body}</CardDescription>
                  </CardHeader>
                </Card>
              </li>
            );
          })}
        </ol>
      </section>

      {/* -------------------------------------------------------- evidence */}
      <section id="evidence" className="scroll-mt-20 border-y bg-card/50">
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="font-heading text-2xl font-semibold tracking-tight">
            Four kinds of statement, never mixed
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            The most common failure in a tool like this is a confident sentence
            with no source attached. BlockTrace keeps four categories apart in
            the data model, in the UI, and in the exported dossier, because they
            do not license the same conclusion.
          </p>

          <dl className="mt-8 grid gap-4 sm:grid-cols-2">
            {EVIDENCE_TIERS.map((tier) => (
              <div key={tier.tag} className={`rounded-xl border p-4 ${tier.className}`}>
                <dt className="font-heading text-sm font-semibold">{tier.tag}</dt>
                <dd className="mt-1.5 text-sm leading-6 opacity-90">{tier.body}</dd>
              </div>
            ))}
          </dl>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Attribution always carries provenance</CardTitle>
              <CardDescription>
                An entity row is a claim about an address. BlockTrace will not
                render one without all of the following attached to it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                {[
                  ["Name", "the entity as the source names it"],
                  ["Address and chain", "which address, on which chain"],
                  ["Type", "exchange, mixer, sanctioned, service…"],
                  ["Source and URL", "where the claim came from, linkable"],
                  ["Verification status", "curated, provider-reported, or heuristic"],
                  ["Date", "when the attribution was recorded"],
                  ["Confidence", "and explicitly zero when unknown"],
                  ["Notes", "what the source did not establish"],
                ].map(([term, detail]) => (
                  <div key={term}>
                    <dt className="font-medium">{term}</dt>
                    <dd className="text-muted-foreground">{detail}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 text-xs leading-5 text-muted-foreground">
                No address in this system was written from memory. If a name is
                not in a source BlockTrace can point at, the address is rendered
                as unattributed — which is a different, and more honest, state.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* --------------------------------------------------------- what it is not */}
      <section className="mx-auto max-w-6xl px-5 py-16">
        <div className="grid gap-8 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <h2 className="font-heading text-2xl font-semibold tracking-tight">
              What a BlockTrace result is not
            </h2>
            <ul className="mt-4 space-y-3 text-sm leading-6">
              {[
                "Not proof of ownership. A risk score describes the data returned for one run, not who controls an address.",
                "Not a legal judgement, and not a compliance determination.",
                "Not a complete picture. Traces are bounded by depth, node count, and provider history — and the result says where it was cut off.",
                "Not live data when the provider is down. An unreachable provider is reported as unreachable, which is the opposite finding of an address with no history.",
              ].map((line) => (
                <li key={line} className="flex gap-2.5">
                  <span className="mt-2 size-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
                  <span className="text-muted-foreground">{line}</span>
                </li>
              ))}
            </ul>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>This deployment</CardTitle>
              <CardDescription>
                Read from the running API, not from this page&apos;s source.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="space-y-2 text-sm">
                {[
                  ["Version", health?.version],
                  ["Access mode", status?.mode],
                  ["Case isolation", status?.mode === "live" ? "per account" : "none"],
                  ["Persistence", health?.persistence],
                  ["Chains", ordered.length ? ordered.join(", ") : null],
                ].map(([term, v]) => (
                  <div key={term} className="flex items-baseline justify-between gap-4">
                    <dt className="shrink-0 text-muted-foreground">{term}</dt>
                    <dd className="min-w-0 text-right font-mono text-xs">
                      <Value>{v}</Value>
                    </dd>
                  </div>
                ))}
              </dl>

              {reachable === false ? (
                <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                  The API did not answer. Everything above is unavailable, and
                  the console will not function until the backend is running.
                  Start it and reload — this page will not fall back to a
                  hard-coded answer.
                </p>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </section>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-5 py-8 text-xs text-muted-foreground">
          <Network className="size-4" aria-hidden="true" />
          <span>BlockTrace</span>
          <span className="text-muted-foreground/50">·</span>
          <span>
            Chain detection, fund-flow tracing, entity intelligence, and risk
            assessment for TRON, Ethereum, BNB Smart Chain, Polygon and Bitcoin.
          </span>
          <Link to="/app/help" className="ml-auto underline-offset-4 hover:underline">
            Method &amp; limitations
          </Link>
        </div>
      </footer>
    </div>
  );
}
