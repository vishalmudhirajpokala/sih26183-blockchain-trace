/**
 * Entity detail — one address, its provenance, and every case it appeared in.
 *
 * This is the page where RULE 4 has to survive scrutiny. An investigator who
 * lands here is deciding whether to act on a label, so everything that makes
 * the claim checkable is shown: the source tier, the source URL, the
 * verification status, the evidence strings the engine recorded, and — when
 * the source URL is absent — an explicit statement that the label is
 * unverified rather than a blank field that could be read as "checked and
 * fine".
 *
 * The route is `/app/entities/:chain/:address`, and a 404 covers both "no
 * trace of this address" and "not yours". Those two are not distinguished,
 * because distinguishing them would confirm the existence of another
 * account's case.
 */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { api } from "@/lib/api";
import {
  chainLabel,
  entityTypeClass,
  entityTypeLabel,
  explorerUrl,
  formatDateTime,
  provenanceTier,
  safeSourceUrl,
  verificationLabel,
} from "@/lib/format";
import {
  AddressChip,
  ErrorPanel,
  EvidenceNotes,
  LoadingBlock,
  NotAvailable,
  PageHeader,
  ProvenanceChip,
  RiskBadge,
  SectionCard,
  StatGrid,
  ValueRow,
} from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function EntityDetail() {
  const { chain, address } = useParams();

  const [entity, setEntity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .entityDetail(chain, address)
      .then(setEntity)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [chain, address]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !entity) {
    return (
      <div className="px-6 py-8">
        <LoadingBlock label="Loading entity" />
      </div>
    );
  }

  if (error) {
    const missing = error.status === 404;
    return (
      <div className="space-y-6 px-6 py-8">
        <PageHeader
          eyebrow="Entities"
          title={missing ? "Not available" : "Could not load this entity"}
          actions={
            <Button variant="outline" render={<Link to="/app/entities" />}>
              <ArrowLeft data-icon="inline-start" />
              All entities
            </Button>
          }
        />
        {missing ? (
          <div className="rounded-lg border border-dashed p-6 text-sm leading-6 text-muted-foreground">
            <p>
              This address is not available to you. That covers two cases — no
              trace you have run attributed it, or the attribution belongs to
              another account — and the response is identical for both so this
              page cannot confirm the existence of a case you are not permitted
              to read.
            </p>
          </div>
        ) : (
          <ErrorPanel error={error} onRetry={load} />
        )}
      </div>
    );
  }

  if (!entity) return null;

  const tier = provenanceTier(entity.provenance_tier);
  const investigations = Array.isArray(entity.investigations)
    ? entity.investigations
    : [];
  const evidence = Array.isArray(entity.evidence) ? entity.evidence : [];
  const sourceUrl = safeSourceUrl(entity.source_url);
  const explorer = explorerUrl(chain, "address", address);

  return (
    <div className="space-y-8 px-6 py-8">
      <PageHeader
        eyebrow={
          <Link to="/app/entities" className="hover:underline">
            Entities
          </Link>
        }
        title={entity.name || "Unattributed address"}
        description={tier.title}
        actions={
          <>
            {explorer ? (
              <Button
                variant="outline"
                render={
                  <a href={explorer} target="_blank" rel="noopener noreferrer" />
                }
              >
                <ExternalLink data-icon="inline-start" />
                View on explorer
              </Button>
            ) : null}
            <Button render={<Link to="/app/trace" />}>Trace this address</Button>
          </>
        }
      />

      <StatGrid
        items={[
          {
            label: "Chain",
            value: entity.chain_name || chainLabel(entity.chain) || entity.chain,
          },
          {
            label: "Type",
            value: (
              <Badge
                variant="outline"
                className={entityTypeClass(entity.type)}
              >
                {entityTypeLabel(entity.type)}
              </Badge>
            ),
          },
          {
            label: "Provenance",
            value: <ProvenanceChip tier={entity.provenance_tier} />,
            tooltip: tier.title,
          },
          {
            label: "Appearances",
            value: entity.investigation_count ?? 0,
            tooltip: "Cases in which this address was seen.",
          },
        ]}
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-6">
          <SectionCard
            title="Provenance"
            description="What this attribution is, and how far it can be trusted."
          >
            <dl className="divide-y">
              <ValueRow label="Address" mono copyable>
                {entity.address}
              </ValueRow>
              <ValueRow label="Name">{entity.name || null}</ValueRow>
              <ValueRow label="Type">{entityTypeLabel(entity.type)}</ValueRow>
              <ValueRow label="Provenance tier">{tier.label}</ValueRow>
              <ValueRow label="Verification">
                {verificationLabel(entity.verification_status)}
              </ValueRow>
              {typeof entity.confidence === "number" ? (
                <ValueRow
                  label="Confidence weight"
                  reason="A fixed weight for this class of attribution — not a probability that the label is correct."
                >
                  {entity.confidence}/100
                </ValueRow>
              ) : null}

              {sourceUrl ? (
                <ValueRow label="Source">
                  <a
                    href={sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 underline underline-offset-4"
                  >
                    {sourceUrl}
                    <ExternalLink className="size-3" aria-hidden="true" />
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

              {entity.verified_at ? (
                <ValueRow label="Verified on">
                  {formatDateTime(entity.verified_at)}
                </ValueRow>
              ) : null}
              {entity.first_seen ? (
                <ValueRow label="First seen">
                  {formatDateTime(entity.first_seen)}
                </ValueRow>
              ) : null}
              {entity.last_seen ? (
                <ValueRow label="Last seen">
                  {formatDateTime(entity.last_seen)}
                </ValueRow>
              ) : null}
            </dl>

            <p className="mt-4 text-sm leading-6 text-muted-foreground">
              {entity.provenance_note}
            </p>
          </SectionCard>

          <SectionCard
            title="Appears in"
            description="Every case of yours in which this address was reached."
          >
            {investigations.length === 0 ? (
              <NotAvailable reason="No saved case lists this address." />
            ) : (
              <div className="overflow-hidden rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Case</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Risk</TableHead>
                      <TableHead className="whitespace-nowrap">Saved</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {investigations.map((inv) => (
                      <TableRow key={inv.id}>
                        <TableCell>
                          <Link
                            to={`/app/investigations/${encodeURIComponent(inv.id)}`}
                            className="block min-w-0"
                          >
                            <span className="block truncate text-sm font-medium">
                              {inv.title || inv.seed || "Untitled"}
                            </span>
                          </Link>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {inv.status || "—"}
                        </TableCell>
                        <TableCell>
                          <RiskBadge
                            level={inv.risk_level}
                            score={inv.risk_score}
                          />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {inv.created_at
                            ? formatDateTime(inv.created_at)
                            : "Not available"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </SectionCard>
        </div>

        <aside className="space-y-6">
          <SectionCard title="Address">
            <AddressChip value={entity.address} chain={entity.chain} />
          </SectionCard>

          {evidence.length ? (
            <EvidenceNotes notes={evidence} title="Evidence" />
          ) : (
            <SectionCard title="Evidence">
              <NotAvailable reason="No evidence strings were recorded for this attribution." />
            </SectionCard>
          )}
        </aside>
      </div>
    </div>
  );
}
