/**
 * Investigations — saved case history, newest first.
 *
 * Every row is a frozen record (`GET /investigations` returns exactly what
 * was stored on save), and a 404 here is deliberate: it covers both a missing
 * id and another user's case, because confirming the latter would confirm the
 * existence of a case the caller is not allowed to see.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import {
  chainLabel,
  formatDateTime,
  statusInfo,
  truncateHash,
} from "@/lib/format";
import {
  EmptyState,
  ErrorPanel,
  PageHeader,
  RiskBadge,
  TableSkeleton,
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

const PAGE_SIZE = 25;

export default function Investigations() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .investigations({ limit: PAGE_SIZE, offset })
      .then((data) => {
        setRows(Array.isArray(data?.items) ? data.items : []);
        setTotal(typeof data?.total === "number" ? data.total : 0);
        setLimit(typeof data?.limit === "number" ? data.limit : PAGE_SIZE);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [offset]);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(row) {
    if (deleting) return;
    // Deleting a case is irreversible and the row is the only record of what
    // was found, so it is confirmed by name rather than removed on one click.
    const confirmed = window.confirm(
      `Delete "${row.title || row.seed}"?\n\n` +
        "This removes the stored investigation. Any PDF already generated stays on disk, " +
        "but this page will no longer list it.",
    );
    if (!confirmed) return;

    setDeleting(row.id);
    try {
      await api.deleteInvestigation(row.id);
      toast.success("Investigation deleted.");
      load();
    } catch (e) {
      toast.error(e.message || "The investigation could not be deleted.");
    } finally {
      setDeleting(null);
    }
  }

  const shown = rows.length;
  const pageStart = total > 0 ? offset + 1 : 0;
  const pageEnd = offset + shown;
  const canPrev = offset > 0;
  const canNext = pageEnd < total;

  return (
    <div className="space-y-6 px-6 py-8">
      <PageHeader
        eyebrow="History"
        title="Investigations"
        description="Every case you have saved, newest first. A saved investigation is a frozen record — it is not re-traced when you open it."
        actions={
          <Button render={<Link to="/app/trace" />}>
            <Plus data-icon="inline-start" />
            New trace
          </Button>
        }
      />

      {error ? <ErrorPanel error={error} onRetry={load} /> : null}

      {loading && rows.length === 0 ? (
        <TableSkeleton rows={6} cols={5} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No investigations yet"
          description="Nothing has been saved to this account. Run a trace from the console, and it will appear here."
          action={
            <Button render={<Link to="/app/trace" />}>
              <Plus data-icon="inline-start" />
              Trace an address
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Chain</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="whitespace-nowrap">Saved</TableHead>
                <TableHead className="w-24 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <Link
                      to={`/app/investigations/${encodeURIComponent(row.id)}`}
                      className="block min-w-0"
                    >
                      <span className="block truncate text-sm font-medium">
                        {row.title || row.seed || "Untitled"}
                      </span>
                      <code
                        className="block truncate font-mono text-[11px] text-muted-foreground"
                        title={row.seed}
                      >
                        {truncateHash(row.seed, 10, 8)}
                      </code>
                    </Link>
                  </TableCell>

                  <TableCell>
                    <Badge variant="secondary">
                      {row.chain_name || chainLabel(row.chain) || row.chain || "Unknown"}
                    </Badge>
                  </TableCell>

                  <TableCell>
                    <RiskBadge level={row.risk_level} score={row.risk_score} />
                  </TableCell>

                  <TableCell>
                    {/*
                      The shared status vocabulary, not the raw enum. This
                      column previously printed `partial` in monospace, which
                      reads as an error code rather than as "this run stopped at
                      its configured scope". The stored value is unchanged and
                      still shown in full on the investigation's details row.
                    */}
                    <span className="text-xs text-muted-foreground">
                      {row.status
                        ? statusInfo(row.status).short
                        : "Not available"}
                    </span>
                  </TableCell>

                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                    {row.created_at ? formatDateTime(row.created_at) : "Not available"}
                  </TableCell>

                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {row.has_report ? (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          render={
                            <Link
                              to={`/app/investigations/${encodeURIComponent(row.id)}`}
                              title="This case has a PDF dossier"
                            />
                          }
                        >
                          <FileText data-icon="inline" />
                          <span className="sr-only">View dossier</span>
                        </Button>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => remove(row)}
                        disabled={deleting === row.id}
                        title="Delete this investigation"
                        aria-label={`Delete ${row.title || row.seed}`}
                      >
                        <Trash2 data-icon="inline" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {total > 0 ? (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            Showing {pageStart}–{pageEnd} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!canPrev || loading}
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!canNext || loading}
              onClick={() => setOffset((o) => o + limit)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
