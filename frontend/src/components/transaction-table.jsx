/**
 * The normalized transaction ledger.
 *
 * Every chain produces this exact shape (`BlockchainTransaction.to_dict()`), so
 * this table has no per-chain branches. That is the whole point of the
 * normalization layer: a TRON transfer in SUN and a Bitcoin transfer in
 * satoshis arrive here already divided into their display unit by their own
 * adapter, with the decimals it reported.
 *
 * Three rules the table keeps:
 *
 * 1. **A missing amount is never a zero.** An outbound transfer with no
 *    counterparty, or one whose value the provider would not report, shows
 *    "Not available" — never `0`, and never the raw integer with no unit.
 * 2. **Self-transfers are shown, not hidden.** An address sending to itself is
 *    one of the most common laundering patterns there is.
 * 3. **Direction is relative to the subject**, and is stated in the header, so
 *    a row is never ambiguous about whose point of view it is written from.
 */

import { Fragment, useMemo, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, ArrowLeftRight } from "lucide-react";

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
import {
  AddressChip,
  HashChip,
  NotAvailable,
  Value,
} from "@/components/common";
import { chainLabel, formatAmount, formatTimestamp } from "@/lib/format";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "incoming", label: "Inbound" },
  { id: "outgoing", label: "Outbound" },
  { id: "self", label: "Self" },
  { id: "failed", label: "Failed" },
];

function DirectionIcon({ direction }) {
  if (direction === "incoming") {
    return <ArrowDownLeft className="size-3.5 text-emerald-600 dark:text-emerald-400" />;
  }
  if (direction === "outgoing") {
    return <ArrowUpRight className="size-3.5 text-orange-600 dark:text-orange-400" />;
  }
  if (direction === "self") {
    return <ArrowLeftRight className="size-3.5 text-amber-600 dark:text-amber-400" />;
  }
  // An unrecognised direction renders as neutral. Guessing "outgoing" because
  // it is the most common would invert the meaning of an unknown row.
  return <ArrowLeftRight className="size-3.5 text-muted-foreground" />;
}

const DIRECTION_LABEL = {
  incoming: "in",
  outgoing: "out",
  self: "self",
};

function matches(tx, filter) {
  if (filter === "all") return true;
  if (filter === "failed") return tx.status === "failed";
  return tx.direction === filter;
}

export function TransactionTable({
  transactions = [],
  chain = null,
  seed = null,
  pageSize = 25,
  className = "",
}) {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState(null);

  const list = useMemo(() => (Array.isArray(transactions) ? transactions : []), [transactions]);

  const filtered = useMemo(() => list.filter((tx) => matches(tx, filter)), [list, filter]);

  // The counterparty is the address that is *not* the subject. Showing both
  // sides separately would be redundant; showing only `to` would make an
  // inbound transfer's counterparty invisible.
  const counterparty = (tx) => {
    if (!seed) return tx.to_address || tx.from_address || null;
    if (tx.from_address === seed && tx.to_address === seed) return tx.from_address;
    if (tx.to_address === seed) return tx.from_address;
    return tx.to_address || tx.from_address;
  };

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pages - 1);
  const rows = filtered.slice(current * pageSize, current * pageSize + pageSize);

  if (list.length === 0) {
    return (
      <div className="px-6 py-10 text-center text-sm text-muted-foreground">
        No normalized transactions were returned for this investigation. That
        is different from a zero balance: read the outcome status and the
        evidence notes above before drawing a conclusion from an empty table.
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-1.5 border-b px-4 py-2.5">
        {FILTERS.map((f) => {
          const count = list.filter((tx) => matches(tx, f.id)).length;
          if (count === 0 && f.id !== "all") return null;
          return (
            <Button
              key={f.id}
              size="sm"
              variant={filter === f.id ? "secondary" : "ghost"}
              onClick={() => {
                setFilter(f.id);
                setPage(0);
              }}
            >
              {f.label}
              <span className="ml-1 text-xs text-muted-foreground">{count}</span>
            </Button>
          );
        })}
        <span className="ml-auto text-xs text-muted-foreground">
          Direction is relative to the traced address
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">
          No transactions match this filter.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-20">Dir</TableHead>
              <TableHead>Transaction</TableHead>
              <TableHead>Counterparty</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead className="whitespace-nowrap">Time</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((tx, i) => {
              const rowKey = `${tx.hash}-${i}`;
              const isOpen = expanded === rowKey;
              const isSelf = tx.direction === "self";
              return (
                <Fragment key={rowKey}>
                  <TableRow className={isSelf ? "bg-amber-50/50 dark:bg-amber-950/20" : undefined}>
                    <TableCell>
                      <span
                        className="flex items-center gap-1.5"
                        title={
                          tx.direction === "incoming"
                            ? "Received by the traced address"
                            : tx.direction === "outgoing"
                              ? "Sent by the traced address"
                              : tx.direction === "self"
                                ? "Sent to itself"
                                : "Direction not reported by the provider"
                        }
                      >
                        <DirectionIcon direction={tx.direction} />
                        <span className="text-xs text-muted-foreground">
                          {DIRECTION_LABEL[tx.direction] ?? "—"}
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      <HashChip value={tx.hash} chain={tx.chain || chain} />
                      {tx.status && tx.status !== "success" ? (
                        <Badge
                          variant="outline"
                          className="ml-2 border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
                        >
                          {tx.status}
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <AddressChip value={counterparty(tx)} chain={tx.chain || chain} lead={10} tail={6} />
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {tx.amount === null || tx.amount === undefined ? (
                        <NotAvailable reason="The provider did not report a value for this transfer." />
                      ) : (
                        <>
                          {formatAmount(tx.amount, tx.decimals, tx.asset)}
                          {tx.token_contract ? (
                            <span className="mt-0.5 block text-[9px] font-normal text-muted-foreground">
                              token {tx.token_contract.slice(0, 8)}…
                            </span>
                          ) : null}
                        </>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      <Value>{tx.timestamp ? formatTimestamp(tx.timestamp) : null}</Value>
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-1.5 text-xs"
                        onClick={() => setExpanded(isOpen ? null : rowKey)}
                      >
                        {isOpen ? "Less" : "More"}
                      </Button>
                    </TableCell>
                  </TableRow>
                  {isOpen ? (
                    <TableRow className="bg-muted/30 hover:bg-muted/30">
                      <TableCell colSpan={6}>
                        <dl className="grid gap-x-6 gap-y-1.5 py-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
                          {[
                            { label: "From", v: tx.from_address },
                            { label: "To", v: tx.to_address },
                            { label: "Status", v: tx.status },
                            { label: "Block", v: tx.block_number },
                            {
                              label: "Fee",
                              v:
                                tx.fee === null || tx.fee === undefined
                                  ? null
                                  : formatAmount(tx.fee, tx.decimals, tx.asset),
                            },
                            { label: "Confirmations", v: tx.confirmations },
                            { label: "Decimals", v: tx.decimals },
                            { label: "Raw amount", v: tx.raw_amount },
                            { label: "Provider", v: tx.provider },
                            { label: "Chain", v: tx.chain ? chainLabel(tx.chain) : null },
                            ...(tx.inputs?.length
                              ? [{ label: "Inputs", v: `${tx.inputs.length} consumed` }]
                              : []),
                            ...(tx.outputs?.length
                              ? [{ label: "Outputs", v: `${tx.outputs.length} produced` }]
                              : []),
                          ].map((row) => (
                            <div key={row.label} className="flex min-w-0 gap-2">
                              <dt className="shrink-0 text-muted-foreground">{row.label}</dt>
                              <dd className="min-w-0 break-all">
                                <Value>{row.v}</Value>
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}

      {pages > 1 ? (
        <div className="flex items-center justify-between border-t px-4 py-2.5 text-xs text-muted-foreground">
          <span>
            Showing {current * pageSize + 1}–{Math.min((current + 1) * pageSize, filtered.length)} of {filtered.length}
          </span>
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" disabled={current === 0} onClick={() => setPage(current - 1)}>
              Previous
            </Button>
            <Button size="sm" variant="outline" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default TransactionTable;
