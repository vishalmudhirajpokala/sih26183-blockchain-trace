"use client"

import * as React from "react"
import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"

import { useIsMobile } from "@/hooks/use-mobile"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group"

export const description = "An interactive area chart"

/**
 * An area chart over whatever series the caller measured.
 *
 * The imported block arrived with 92 rows of invented April–June 2024 visitor
 * traffic, two demo series ("desktop" / "mobile"), and a hard-coded
 * `new Date("2024-06-30")` to anchor its 7/30/90-day window. All three are gone:
 *
 *   - There is no bundled sample data. An empty `data` renders `emptyMessage`,
 *     never a placeholder curve. This mattered in practice: while wiring the
 *     dashboard, a deployment that reported no timeline fell back to the sample
 *     and drew a confident visitor trend out of nothing.
 *   - `series` names the keys actually plotted and `labels` names them for the
 *     reader, because a chart cannot invent a unit it was not given. With no
 *     `series`, the keys are read off the first row minus `date`.
 *   - The window is anchored to the newest point in `data`, not to a literal
 *     date, so "last 7 days" means the last 7 days of the record.
 */
export function ChartAreaInteractive({
  data = [],
  series,
  labels = {},
  title = "Investigations over time",
  caption = "Total for the last 3 months",
  captionShort = "Last 3 months",
  emptyMessage = "No data for this period.",
}) {
  const isMobile = useIsMobile()
  const [timeRange, setTimeRange] = React.useState("90d")

  React.useEffect(() => {
    if (isMobile) {
      setTimeRange("7d")
    }
  }, [isMobile])

  const rows = React.useMemo(() => (Array.isArray(data) ? data : []), [data])

  // With no explicit `series`, plot every measured key the first row carries,
  // minus the x-axis itself. Nothing is invented and nothing is hard-coded.
  const keys = React.useMemo(() => {
    if (Array.isArray(series) && series.length > 0) return series
    const first = rows[0]
    if (!first) return []
    return Object.keys(first).filter((k) => k !== "date")
  }, [series, rows])

  const filteredData = React.useMemo(() => {
    // The window is measured back from the newest point in the data, so the
    // toggles mean the same thing on any day and for any dataset.
    const times = rows
      .map((item) => new Date(item.date).getTime())
      .filter((t) => !Number.isNaN(t))
    if (times.length === 0) return rows

    const referenceDate = new Date(Math.max(...times))
    let daysToSubtract = 90
    if (timeRange === "30d") {
      daysToSubtract = 30
    } else if (timeRange === "7d") {
      daysToSubtract = 7
    }
    const startDate = new Date(referenceDate)
    startDate.setDate(startDate.getDate() - daysToSubtract)
    return rows.filter((item) => new Date(item.date) >= startDate)
  }, [rows, timeRange])

  return (
    <Card className="@container/card">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          <span className="hidden @[540px]/card:block">
            {caption}
          </span>
          <span className="@[540px]/card:hidden">{captionShort || caption}</span>
        </CardDescription>
        <CardAction>
          <ToggleGroup
            multiple={false}
            value={timeRange ? [timeRange] : []}
            onValueChange={(value) => {
              setTimeRange(value[0] ?? "90d")
            }}
            variant="outline"
            className="hidden *:data-[slot=toggle-group-item]:px-4! @[767px]/card:flex"
          >
            <ToggleGroupItem value="90d">Last 3 months</ToggleGroupItem>
            <ToggleGroupItem value="30d">Last 30 days</ToggleGroupItem>
            <ToggleGroupItem value="7d">Last 7 days</ToggleGroupItem>
          </ToggleGroup>
          <Select
            value={timeRange}
            onValueChange={(value) => {
              if (value !== null) {
                setTimeRange(value)
              }
            }}
          >
            <SelectTrigger
              className="flex w-40 **:data-[slot=select-value]:block **:data-[slot=select-value]:truncate @[767px]/card:hidden"
              size="sm"
              aria-label="Select a value"
            >
              <SelectValue placeholder="Last 3 months" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              <SelectItem value="90d" className="rounded-lg">
                Last 3 months
              </SelectItem>
              <SelectItem value="30d" className="rounded-lg">
                Last 30 days
              </SelectItem>
              <SelectItem value="7d" className="rounded-lg">
                Last 7 days
              </SelectItem>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        {filteredData.length === 0 ? (
          <p className="flex h-[250px] items-center justify-center text-sm text-muted-foreground">
            {emptyMessage}
          </p>
        ) : (
        <ChartContainer
          config={Object.fromEntries(
            keys.map((key) => [key, { label: labels[key] || key, color: "var(--primary)" }])
          )}
          className="aspect-auto h-[250px] w-full"
        >
          <AreaChart data={filteredData}>
            <defs>
              {keys.map((key) => (
                <linearGradient key={key} id={`fill-${key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor={`var(--color-${key})`}
                    stopOpacity={1.0}
                  />
                  <stop
                    offset="95%"
                    stopColor={`var(--color-${key})`}
                    stopOpacity={0.1}
                  />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={32}
              tickFormatter={(value) => {
                const date = new Date(value)
                return date.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                })
              }}
            />
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  labelFormatter={(value) => {
                    return new Date(value).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    })
                  }}
                  indicator="dot"
                />
              }
            />
            {keys.map((key) => (
              <Area
                key={key}
                dataKey={key}
                type="natural"
                fill={`url(#fill-${key})`}
                stroke={`var(--color-${key})`}
                stackId="a"
              />
            ))}
          </AreaChart>
        </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
