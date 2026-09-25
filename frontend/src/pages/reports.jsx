/**
 * Reports — the generated PDF dossiers.
 *
 * Reports are not a separate store. `GET /reports` is a view over saved
 * investigations filtered to those that produced a PDF, which is why every row
 * here is also a row in Investigations and why the list can be empty while
 * investigations exist.
 *
 * The one action on this page is "re-render", and the copy says what it is:
 * a fresh PDF from the *stored* result. It is not a re-trace, so the dossier
 * cannot silently start describing a different moment than the case on screen.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, FileText, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";

import { api, reportHref } from "@/lib/api";
import { chainLabel, formatDateTime } from "@/lib/format";
import {
  EmptyState,
  ErrorPanel,
  PageHeader,
  RiskBadge,
  SectionCard,
  TableSkeleton,
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

export default function Reports() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(25);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .reports({ limit: 25, offset })
      .then((data) => {
        setRows(Array.isArray(data?.items) ? data.items : []);
        setTotal(typeof data?.total === "number" ? data.total : 0);
        setLimit(typeof data?.limit === "number" ? data.limit : 25);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [offset]);

  useEffect(() => {
    load();
  }, [load]);

  async function regenerate(row) {
    if (busy) return;
    setBusy(row.investigation_id);
    try {
      const res = await api.regenerateReport(row.investigation_id);
      setRows((prev) =>
        prev.map((r) =>
          r.investigation_id === row.investigation_id
            ? { ...r, report_url: res.report_url, has_report: true }
            : r,
        ),
      );
      toast.success("Re-rendered from the stored result.");
    } catch (e) {
      toast.error(e.message || "The dossier could not be re-rendered.");
    } finally {
      setBusy(null);
    }
  }

  const pageEnd = offset + rows.length;

  return (
    <div className="space-y-6 px-6 py-8">
      <PageHeader
        eyebrow="Dossiers"
        title="Reports"
        description="PDF dossiers generated from saved investigations. Each one is a rendering of a frozen result, not a second run of the trace."
        actions={
          <Button variant="outline" render={<Link to="/app/investigations" />}>
            All investigations
          </Button>
        }
      />

      {error ? <ErrorPanel error={error} onRetry={load} /> : null}

      {loading && rows.length === 0 ? (
        <TableSkeleton rows={5} cols={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No dossiers generated yet"
          description="A dossier is produced when a trace completes and renders. Run a trace from the console, then return here to download it."
          action={
            <Button render={<Link to="/app/trace" />}>
              <Search data-icon="inline-start" />
              Run a trace
            </Button>
          }
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Case</TableHead>
                  <TableHead>Chain</TableHead>
                  <TableHead>Risk</TableHead>
                  <TableHead className="whitespace-nowrap">Generated</TableHead>
                  <TableHead className="w-32 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const href = reportHref(row.report_url);
                  return (
                    <TableRow key={row.investigation_id}>
                      <TableCell>
                        <Link
                          to={`/app/investigations/${encodeURIComponent(row.investigation_id)}`}
                          className="block min-w-0"
                        >
                          <span className="block truncate text-sm font-medium">
                            {row.title || row.seed || "Untitled"}
                          </span>
                          <span className="block truncate font-mono text-[11px] text-muted-foreground">
                            {row.seed || "No seed recorded"}
                          </span>
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

                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {row.created_at ? formatDateTime(row.created_at) : "Not available"}
                      </TableCell>

                      <TableCell>
                        <div className="flex items-center justify-end gap-1">
                          {href ? (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              render={
                                <a href={href} target="_blank" rel="noopener noreferrer" title="Download the PDF" />
                              }
                            >
                              <Download data-icon="inline" />
                              <span className="sr-only">Download</span>
                            </Button>
                          ) : null}
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            onClick={() => regenerate(row)}
                            disabled={busy === row.investigation_id}
                            title="Re-render from the stored result. This does not re-trace."
                            aria-label="Re-render"
                          >
                            <RefreshCw
                              data-icon="inline"
                              className={busy === row.investigation_id ? "animate-spin" : undefined}
                            />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          {total > 0 ? (
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                Showing {offset + 1}–{pageEnd} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={offset === 0 || loading}
                  onClick={() => setOffset((o) => Math.max(0, o - limit))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pageEnd >= total || loading}
                  onClick={() => setOffset((o) => o + limit)}
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}

      <SectionCard title="What a dossier is">
        <ValueRow label="Generated from" copyable>
          The stored TraceResult, exactly as saved.
        </ValueRow>
        <ValueRow label="Re-rendered from">
          The same stored result. Chain state may have changed since the trace ran; the stored data is unchanged.
        </ValueRow>
        <ValueRow label="Never does">
          Re-trace. A re-run would return a different graph describing a different moment, attached to the same case id.
        </ValueRow>
      </SectionCard>
    </div>
  );
}
