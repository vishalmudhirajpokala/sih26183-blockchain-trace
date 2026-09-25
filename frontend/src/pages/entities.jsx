/**
 * Entity intelligence — every address this account's traces attributed.
 *
 * RULE 4 governs this page, so the list is built to make a weak attribution
 * *look* weak. Each row carries its provenance tier and whether a citable
 * source exists, and an attribution with no source URL is dimmed rather than
 * shown at the same weight as a curated one — because "Binance Hot Wallet 6"
 * and "a string the provider returned" are not the same kind of claim, and a
 * table that renders them identically misleads by layout alone.
 *
 * The type filter is populated from `GET /entities/types`, which reports only
 * types that actually occur in this account's data. It is deliberately not a
 * hard-coded list of entity categories: a filter offering "mixer" when no
 * mixer has been seen implies one might exist.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Users } from "lucide-react";

import { api } from "@/lib/api";
import {
  CHAIN_ORDER,
  chainLabel,
  entityTypeClass,
  entityTypeLabel,
  formatDateTime,
  truncateHash,
  verificationLabel,
} from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  EmptyState,
  ErrorPanel,
  PageHeader,
  ProvenanceChip,
  SectionCard,
  TableSkeleton,
} from "@/components/common";

const PAGE_SIZE = 50;

export default function Entities() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [types, setTypes] = useState(null);
  const [typeFilter, setTypeFilter] = useState(null);
  const [chainFilter, setChainFilter] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .entities({
        limit: PAGE_SIZE,
        offset,
        entity_type: typeFilter || undefined,
        chain: chainFilter || undefined,
      })
      .then((data) => {
        setRows(Array.isArray(data?.items) ? data.items : []);
        setTotal(typeof data?.total === "number" ? data.total : 0);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [offset, typeFilter, chainFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    api
      .entityTypes()
      .then((data) => {
        if (!cancelled) setTypes(data);
      })
      // A missing type list only costs the filter. It is not a reason to hide
      // the entities themselves, so the failure is not surfaced as a page error.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // A filter change invalidates the current page window.
  function applyFilter(setter) {
    return (next) => {
      setter(next ?? null);
      setOffset(0);
    };
  }

  const typeOptions = types?.types || [];
  const filtered = typeFilter || chainFilter;
  const pageEnd = offset + rows.length;

  return (
    <div className="space-y-6 px-6 py-8">
      <PageHeader
        eyebrow="Attribution"
        title="Entity intelligence"
        description="Addresses your own traces attributed, each with where the attribution came from. Nothing here is pre-seeded: an address appears because a trace you ran surfaced it."
      />

      <SectionCard
        title="Filters"
        description="Types are drawn from what this account has actually observed."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="entity-type">Entity type</Label>
            {/* `null` is the "no selection" value. Passing "" here would make
                the API omit the filter anyway, but it also renders as an
                empty-looking trigger rather than the placeholder. */}
            <Select
              value={typeFilter}
              onValueChange={applyFilter(setTypeFilter)}
            >
              <SelectTrigger id="entity-type" className="w-full">
                <SelectValue placeholder="All observed types" />
              </SelectTrigger>
              <SelectContent>
                {typeOptions.map((t) => (
                  <SelectItem key={t.type} value={t.type}>
                    {entityTypeLabel(t.type)} ({t.count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="entity-chain">Chain</Label>
            <Select
              value={chainFilter}
              onValueChange={applyFilter(setChainFilter)}
            >
              <SelectTrigger id="entity-chain" className="w-full">
                <SelectValue placeholder="All chains" />
              </SelectTrigger>
              <SelectContent>
                {CHAIN_ORDER.map((c) => (
                  <SelectItem key={c} value={c}>
                    {chainLabel(c)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {typeOptions.length === 0 && types ? (
          <p className="mt-3 text-xs text-muted-foreground">
            No entity types have been observed yet. {types.note}
          </p>
        ) : null}
      </SectionCard>

      {error ? <ErrorPanel error={error} onRetry={load} /> : null}

      {loading && rows.length === 0 ? (
        <TableSkeleton rows={6} cols={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Users}
          title={filtered ? "No entities match these filters" : "No entities attributed yet"}
          description={
            filtered
              ? "Nothing in your investigations matches that combination. Clearing a filter may show more."
              : "Entity rows are created when a trace resolves a label for an address. Run a trace on an address that transacts with a known service, exchange, or mixer."
          }
          action={
            filtered ? (
              <Button
                variant="outline"
                onClick={() => {
                  setTypeFilter(null);
                  setChainFilter(null);
                  setOffset(0);
                }}
              >
                Clear filters
              </Button>
            ) : (
              <Button render={<Link to="/app/trace" />}>Run a trace</Button>
            )
          }
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Entity</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Address</TableHead>
                  <TableHead>Provenance</TableHead>
                  <TableHead>Verification</TableHead>
                  <TableHead className="whitespace-nowrap">Last seen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={`${row.chain}-${row.address}`}
                    // An unsourced label is dimmed rather than dropped: the
                    // address is still evidence, it just does not license the
                    // name beside it. Hiding it would hide the gap.
                    className={row.has_citable_source ? undefined : "opacity-60"}
                  >
                    <TableCell>
                      <Link
                        to={`/app/entities/${encodeURIComponent(row.chain)}/${encodeURIComponent(row.address)}`}
                        className="block min-w-0"
                      >
                        <span className="block truncate text-sm font-medium">
                          {row.name || "Unattributed address"}
                        </span>
                        {row.source_url ? (
                          <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                            Source
                            <ExternalLink className="size-2.5" aria-hidden="true" />
                          </span>
                        ) : null}
                      </Link>
                    </TableCell>

                    <TableCell>
                      <Badge
                        variant="outline"
                        className={entityTypeClass(row.type)}
                      >
                        {entityTypeLabel(row.type)}
                      </Badge>
                    </TableCell>

                    <TableCell>
                      <code
                        className="font-mono text-xs text-muted-foreground"
                        title={row.address}
                      >
                        {truncateHash(row.address, 8, 6)}
                      </code>
                      <span className="ml-2 text-[11px] text-muted-foreground">
                        {chainLabel(row.chain) || row.chain}
                      </span>
                    </TableCell>

                    <TableCell>
                      <ProvenanceChip tier={row.provenance_tier} />
                    </TableCell>

                    <TableCell className="text-xs">
                      {verificationLabel(row.verification_status)}
                      {typeof row.confidence === "number" ? (
                        <span
                          className="ml-1 font-mono text-muted-foreground"
                          title="A fixed weight for this class of attribution — not a probability that the label is correct."
                        >
                          {row.confidence}/100
                        </span>
                      ) : null}
                    </TableCell>

                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {row.last_seen ? formatDateTime(row.last_seen) : "Not available"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {total > PAGE_SIZE ? (
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                Showing {offset + 1}–{pageEnd} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset === 0 || loading}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pageEnd >= total || loading}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
