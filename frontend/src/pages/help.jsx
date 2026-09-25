/**
 * Method & limitations.
 *
 * This page exists because the product's most dangerous failure mode is not a
 * crash — it is a plausible-looking answer that a reader cannot audit. A tool
 * that tells an investigator how it reached a conclusion, and what it cannot
 * tell them, is part of the tool. So the limitations are stated as plainly as
 * the capabilities, and they are not behind a disclosure triangle.
 *
 * The four evidence tiers and the four provenance tiers are the vocabulary the
 * rest of the UI is built on; both are spelled out here in full rather than
 * cross-referenced, because this is the page a reader lands on when they need to
 * know what a badge in a table actually means.
 */

import { Link } from "react-router-dom";
import { ArrowRight, BookOpen } from "lucide-react";

import { PageHeader, SectionCard, ValueRow } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** The four evidence tiers, weakest claim last. */
const EVIDENCE_TIERS = [
  {
    name: "Fact",
    description:
      "Retrieved from a chain or a provider and reproduced exactly: a transaction hash, a block height, an address, a transfer amount. A fact can be checked against an explorer and will match.",
  },
  {
    name: "Attribution",
    description:
      "A claim about what an address *is* — an exchange, a sanctioned entity, a mixer. An attribution is only as good as its provenance, so it always arrives with a source or an explicit statement that it has none.",
  },
  {
    name: "Signal",
    description:
      "A pattern observed in the data, such as many small hops followed by one large outgoing transfer. A signal is a reason to look closer. It is not itself a finding.",
  },
  {
    name: "Interpretation",
    description:
      "An engine's or an analyst's reading of the signals — a risk score, a narrative about intent. This is the weakest tier and is always labelled as such. It is never presented as an observation.",
  },
];

/** The four provenance tiers, strongest first. */
const PROVENANCE_TIERS = [
  {
    tier: "curated_verified",
    label: "Curated, verified",
    description:
      "Checked against a maintained published source. The source URL is shown so the check can be repeated. An entry in this tier with no source URL is downgraded and shown as unverified — an attribution with nothing to check is not evidence.",
  },
  {
    tier: "public_provider",
    label: "Public provider",
    description:
      "A block explorer's own label for an address, reproduced. That is the provider's claim, not an independent verification of the entity's identity or conduct.",
  },
  {
    tier: "heuristic",
    label: "Heuristic",
    description:
      "Inferred from the shape of the traffic rather than from a source. Treat as a lead to investigate, not a finding to report.",
  },
  {
    tier: "none",
    label: "No attribution",
    description:
      "The address is known only by its behaviour in the transactions that were retrieved. No claim is made about who owns it.",
  },
];

const LIMITATIONS = [
  {
    title: "A trace describes a moment, not a history",
    body: "Block explorers expose what a provider has indexed at the time of the query. A saved investigation is a frozen record of one retrieval. Re-opening a case never re-queries a chain, because a case that silently changed shape would no longer be the thing you investigated.",
  },
  {
    title: "Truncation is not a clean result",
    body: "A trace stops at a depth limit, a transaction cap, or a time budget. When it does, the result is marked partial or truncated and the reason is shown at the top of the case. Absence of a counterparty in a partial graph is not evidence that the subject never transacted with one.",
  },
  {
    title: "Attribution is a claim, not a verdict",
    body: "Classifying an address does not establish who controls it, whether the label is current, or whether the entity behind it has done anything. A sanctioned label on an address is a reason to escalate, not a conclusion.",
  },
  {
    title: "Risk scores are this engine's own",
    body: "A score summarises signals this system found. It is not a regulatory rating, not a market measure, and not comparable to any external scoring system. The signals behind it are always shown alongside it.",
  },
  {
    title: "Missing data is reported, not filled in",
    body: "A metric a provider does not expose is shown as not available. A provider that cannot be reached is shown as unreachable. Neither is ever rendered as a zero, and nothing on any page is estimated or interpolated to make a table look complete.",
  },
  {
    title: "Analytics describe your cases, not the chain",
    body: "Every figure on the analytics page is computed from investigations you ran. It is not market data, not a chain-wide metric, and not derived from any provider beyond those used for your own traces.",
  },
  {
    title: "Cases are scoped to your account",
    body: "A case you cannot read returns the same response as a case that does not exist, so this tool cannot be used to confirm that another investigator's case is real.",
  },
];

export default function Help() {
  return (
    <div className="space-y-8 px-6 py-8">
      <PageHeader
        eyebrow="Documentation"
        title="Method & limitations"
        description="How this tool reaches its conclusions, what each label means, and — at least as importantly — what it cannot tell you."
        actions={
          <Button render={<Link to="/app/trace" />}>
            <ArrowRight data-icon="inline-start" />
            Run a trace
          </Button>
        }
      />

      <SectionCard
        title="How a trace works"
        description="Six stages, in order. Each stage can fail on its own, and a stage that fails is reported rather than hidden."
      >
        <ol className="space-y-4 text-sm leading-6 text-muted-foreground">
          <li>
            <strong className="text-foreground">Detect.</strong> The input is
            classified as an address or a transaction hash, and the chain is
            determined from its format. An input that matches no supported chain
            is rejected rather than guessed at.
          </li>
          <li>
            <strong className="text-foreground">Retrieve.</strong> The
            address's transaction history is read from the providers configured
            for that chain. Provider-side failures are surfaced as failures; they
            are never treated as an address with no history.
          </li>
          <li>
            <strong className="text-foreground">Expand.</strong> Counterparties
            are followed outward hop by hop until the depth, transaction, or time
            limit is reached. Which addresses are followed is a setting on the
            trace, not a hidden default.
          </li>
          <li>
            <strong className="text-foreground">Normalize.</strong> Every
            transfer becomes the same internal record regardless of chain, so
            the table, the graph, and the dossier need no per-chain special
            cases and cannot disagree with one another.
          </li>
          <li>
            <strong className="text-foreground">Attribute.</strong> Each address
            is matched against curated records and provider labels. Anything
            matched is tagged with where the match came from and whether a
            source can be checked.
          </li>
          <li>
            <strong className="text-foreground">Assess.</strong> Signals in the
            graph produce a risk score with the signals shown beside it, plus
            evidence notes recording what was and was not established.
          </li>
        </ol>
      </SectionCard>

      <SectionCard
        title="Evidence tiers"
        description="Every statement this tool makes sits in one of four tiers, and the UI marks which one you are reading."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {EVIDENCE_TIERS.map((tier, i) => (
            <div key={tier.name} className="rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{i + 1}</Badge>
                <span className="text-sm font-medium">{tier.name}</span>
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {tier.description}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">
          These tiers are ordered by how independently checkable they are. A
          lower tier is not worthless — it is a different kind of claim, and
          conflating them is how a lead becomes an accusation by accident.
        </p>
      </SectionCard>

      <SectionCard
        title="Provenance tiers"
        description="What each attribution badge on an entity is worth. This is the vocabulary behind the Provenance chips in the entity tables."
      >
        <dl className="divide-y">
          {PROVENANCE_TIERS.map((p) => (
            <ValueRow
              key={p.tier}
              label={p.label}
              mono={false}
              reason={p.description}
            >
              {p.tier}
            </ValueRow>
          ))}
        </dl>
      </SectionCard>

      <SectionCard
        title="Limitations"
        description="Stated up front, because an investigator who does not know these will over-read the results."
      >
        <div className="space-y-5">
          {LIMITATIONS.map((item) => (
            <div key={item.title} className="border-l-2 border-border pl-4">
              <p className="text-sm font-medium">{item.title}</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Data sources">
        <p className="text-sm leading-6 text-muted-foreground">
          Data comes from public block explorers and, where configured, from
          provider APIs. Every provider call made during a trace is recorded in
          that case's provider ledger, including calls that failed, so the cost
          and the completeness of a run can be audited after the fact.
        </p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          The Network page shows which providers are reachable right now and
          which metrics each one does not expose. It is the fastest way to tell
          a genuinely quiet address from one whose history could not be
          retrieved.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" render={<Link to="/app/network" />}>
            <BookOpen data-icon="inline-start" />
            Network status
          </Button>
          <Button variant="outline" render={<Link to="/app/entities" />}>
            Entity intelligence
          </Button>
        </div>
      </SectionCard>
    </div>
  );
}
