"use client"

import { TrendingUpIcon, TrendingDownIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { NOT_AVAILABLE } from "@/lib/format"

/**
 * The Dashboard 01 stat row.
 *
 * The imported block shipped this with four hard-coded cards — "Total Revenue
 * $1,250.00", "New Customers 1,234" and so on — and no props at all. In a
 * forensic console those numbers would be an assertion about evidence that no
 * measurement supports, so the cards are now driven entirely by `stats` and
 * the literals are gone.
 *
 * `stats` is a list of at most four entries:
 *
 *   { label, value, trend?, note? }
 *
 * `value` is expected to be an already-formatted string or a number, because
 * formatting is the caller's decision: BlockTrace's counters come from
 * `formatCount` and its scores from the risk engine, and this component has no
 * business reformatting either. A missing value renders as `NOT_AVAILABLE`,
 * which is the same word the rest of the app uses for "the API did not report
 * this" — it is never replaced with a placeholder digit.
 *
 * `trend` is optional and is shown only when supplied, so a card whose
 * comparison is unknown shows no badge rather than a fabricated delta.
 */
export function SectionCards({ stats }) {
  const cards = Array.isArray(stats) ? stats.slice(0, 4) : []

  // Nothing to state. Rendering the block's original placeholder cards here
  // would put invented figures back on the page, so the row is simply absent.
  if (cards.length === 0) return null

  return (
    /*
     * The block's original breakpoints were the container queries
     * `@xl/main:` and `@5xl/main:`, which measure a container named `main`.
     * `ui/sidebar.jsx` renders `SidebarInset` as a bare `<main>` with no
     * `@container/main` on it, so those queries never match and the row would
     * stay one column at every width. `sm:`/`xl:` give the same 1 → 2 → 4
     * progression against the viewport instead.
     */
    <div className="grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-linear-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs lg:px-6 sm:grid-cols-2 xl:grid-cols-4 dark:*:data-[slot=card]:bg-card">
      {cards.map((card) => {
        const TrendIcon = card.trend?.direction === "down" ? TrendingDownIcon : TrendingUpIcon
        const hasValue = card.value !== null && card.value !== undefined && card.value !== ""

        return (
          <Card key={card.label} className="@container/card">
            <CardHeader>
              <CardDescription>{card.label}</CardDescription>
              <CardTitle
                className={
                  hasValue
                    ? "text-2xl font-semibold tabular-nums @[250px]/card:text-3xl"
                    : "text-2xl font-semibold text-muted-foreground @[250px]/card:text-3xl"
                }
              >
                {hasValue ? card.value : NOT_AVAILABLE}
              </CardTitle>
              {card.trend ? (
                <CardAction>
                  <Badge variant="outline">
                    <TrendIcon />
                    {card.trend.label}
                  </Badge>
                </CardAction>
              ) : null}
            </CardHeader>
            {card.note || card.trend ? (
              <CardFooter className="flex-col items-start gap-1.5 text-sm">
                {card.trend ? (
                  <div className="line-clamp-1 flex gap-2 font-medium">
                    {card.trend.note || card.trend.label}{" "}
                    <TrendIcon className="size-4" />
                  </div>
                ) : null}
                {card.note ? (
                  <div className="text-muted-foreground">{card.note}</div>
                ) : null}
              </CardFooter>
            ) : null}
          </Card>
        )
      })}
    </div>
  )
}
