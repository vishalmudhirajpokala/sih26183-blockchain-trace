/**
 * The fund-flow graph.
 *
 * Two renderers, one data source:
 *
 * - **2D (default).** A layered SVG. Layered rather than force-directed
 *   because the engine already knows the depth of every node, and depth is the
 *   single most useful spatial fact in a fund-flow trace: left to right is
 *   distance from the subject. A force layout discards that information to
 *   produce a prettier picture, which is the wrong trade for a forensic tool.
 *   It also prints, screenshots, and works without WebGL.
 * - **3D.** Loaded on demand. A rotating scene is genuinely useful for
 *   understanding a wide graph's shape, and genuinely bad at answering "who
 *   sent to whom".
 *
 * Colour encodes *entity type*, never risk score. Risk is rendered as a badge
 * on the node, because a red node is read as "dangerous address", and that is
 * a claim about the address rather than about this investigation. Only the
 * subject under investigation is genuinely red — and it is red because it is
 * the starting point, not because it was judged.
 */

import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Box, Minus, NetworkIcon, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  Value,
} from "@/components/common";
import {
  chainLabel,
  entityTypeLabel,
  formatAmount,
  safeSourceUrl,
  truncateHash,
} from "@/lib/format";
import { Disclosure } from "@/components/common";

const FundFlow3D = lazy(() => import("@/components/fund-flow-3d"));

// ---------------------------------------------------------------------------
// COLOUR
// ---------------------------------------------------------------------------

/**
 * Node colour by entity type, using the same scale as the entity chips
 * elsewhere in the app. An unclassified address is deliberately the neutral
 * one: "we have no attribution" must not look like a category of its own.
 */
const ENTITY_COLOR = {
  exchange: "#3b82f6",
  mixer: "#a855f7",
  sanctioned: "#ef4444",
  high_risk: "#f97316",
  service: "#64748b",
  unknown: "#64748b",
};

const SUBJECT_COLOR = "#ef4444";

function nodeColor(node) {
  if (node.is_seed) return SUBJECT_COLOR;
  return ENTITY_COLOR[node.entity_type] ?? ENTITY_COLOR.unknown;
}

function nodeRadius(node) {
  // Area ∝ total volume, so the size reads as "how much activity", not as an
  // arbitrary ranking. Clamped because one busy address should not shrink the
  // rest of the graph to dots.
  const volume = (node.inbound || 0) + (node.outbound || 0);
  if (volume <= 0) return 9;
  return Math.min(26, 9 + Math.sqrt(volume) * 3.2);
}

// ---------------------------------------------------------------------------
// LAYOUT
// ---------------------------------------------------------------------------

/**
 * Assign each node an (x, y) on a left-to-right depth grid.
 *
 * Nodes are grouped by `depth`, which the engine sets as the hop distance from
 * the subject. Within a layer they are stacked and centred, so the picture
 * reads as "hop 0 → hop 1 → hop 2" with no legend required.
 */
function useLayout(nodes, width, height) {
  return useMemo(() => {
    if (!nodes.length) return { positions: new Map(), width, height };

    const maxDepth = Math.max(...nodes.map((n) => n.depth || 0), 0);
    // A single layer should sit in the middle rather than hug the left edge.
    const columns = maxDepth + 1;
    const marginX = 78;
    const marginY = 46;
    const usableW = Math.max(width - marginX * 2, 120);
    const usableH = Math.max(height - marginY * 2, 80);
    const colWidth = columns > 1 ? usableW / (columns - 1) : 0;

    const layers = new Map();
    for (const node of nodes) {
      const d = node.depth || 0;
      if (!layers.has(d)) layers.set(d, []);
      layers.get(d).push(node);
    }

    const positions = new Map();
    for (const [depth, layer] of layers) {
      const x = marginX + colWidth * depth;
      const step = usableH / (layer.length + 1);
      layer.forEach((node, i) => {
        positions.set(node.address, {
          x,
          y: marginY + step * (i + 1),
        });
      });
    }

    return { positions, width, height };
  }, [nodes, width, height]);
}

/** A curved path between two laid-out nodes, with an arrowhead. */
function edgePath(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.hypot(dx, dy) || 1;
  // Start and end on the circle edge, not at the centre, so the line does not
  // disappear under the node.
  const r1 = 11;
  const r2 = 11;
  const x1 = from.x + (dx / dist) * r1;
  const y1 = from.y + (dy / dist) * r1;
  const x2 = to.x - (dx / dist) * r2;
  const y2 = to.y - (dy / dist) * r2;
  // Bow the line perpendicular to its run. Two transfers between the same
  // pair then render as two distinct arcs instead of overlapping.
  const bow = Math.min(34, dist * 0.13);
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const cx = mx - (dy / dist) * bow;
  const cy = my + (dx / dist) * bow;
  return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
}

function edgeMidpoint(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const dist = Math.hypot(dx, dy) || 1;
  const bow = Math.min(34, dist * 0.13);
  return {
    x: (from.x + to.x) / 2 - (dy / dist) * bow * 0.5,
    y: (from.y + to.y) / 2 + (dx / dist) * bow * 0.5,
  };
}

// ---------------------------------------------------------------------------
// 2D GRAPH
// ---------------------------------------------------------------------------

const VIEW_W = 960;
const VIEW_H = 520;

/*
 * Above this many edges meeting at one address, the individual value labels are
 * replaced by a single aggregate.
 *
 * Eight is where a real trace stopped being readable: a hop-2 trace of the WETH
 * contract produced 119 edges, and labelling each one put every string in a
 * narrow band through the middle of the canvas. The threshold is about how many
 * labels a reader can hold in view at once, not about the data.
 */
const EDGE_LABEL_MAX = 8;

/** The centre of the viewport in client coordinates, for the +/- buttons. */
function pointerCentre(svg) {
  if (!svg) return [0, 0];
  const r = svg.getBoundingClientRect();
  return [r.left + r.width / 2, r.top + r.height / 2];
}

/** A pointer position converted to world (untransformed) coordinates. */
function toWorld(event, svg, cam) {
  if (!svg) return { x: 0, y: 0 };
  const r = svg.getBoundingClientRect();
  const vx = ((event.clientX - r.left) / r.width) * VIEW_W;
  const vy = ((event.clientY - r.top) / r.height) * VIEW_H;
  return { x: (vx - cam.x) / cam.k, y: (vy - cam.y) / cam.k };
}

/** The bounding box of every laid-out node, used by Fit. */
function graphBounds(positions) {
  if (positions.size === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of positions.values()) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  return { x: minX, y: minY, width: Math.max(maxX - minX, 1), height: Math.max(maxY - minY, 1) };
}

function Graph2D({ nodes, edges, onSelect }) {
  const laidOut = useLayout(nodes, VIEW_W, VIEW_H);

  // Node positions are state, not a pure memo, so a node can be dragged and
  // stay where it was put. The initial value is the computed layout; dragging
  // only ever writes user-driven coordinates on top of it.
  const [dragged, setDragged] = useState({});
  const positions = useMemo(() => {
    const merged = new Map(laidOut.positions);
    for (const [address, at] of Object.entries(dragged)) merged.set(address, at);
    return merged;
  }, [laidOut.positions, dragged]);

  const [hover, setHover] = useState(null);
  // A clicked node stays focused after the pointer leaves, so a value label can
  // be read without holding the mouse still over a nine-pixel target.
  const [pinned, setPinned] = useState(null);
  const [edgeHover, setEdgeHover] = useState(null);
  const focusNode = hover || pinned;

  /*
   * The camera. A plain transform on one `<g>`, so the world stays larger than
   * the viewport and the user moves around it -- wheel zooms about the pointer,
   * dragging the background pans, dragging a node moves only that node.
   */
  const svgRef = useRef(null);
  const [cam, setCam] = useState({ k: 1, x: 0, y: 0 });
  const gesture = useRef(null);

  const zoomAbout = (clientX, clientY, factor) => {
    const el = svgRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Where the pointer is in viewBox units, before the transform.
    const px = ((clientX - rect.left) / rect.width) * VIEW_W;
    const py = ((clientY - rect.top) / rect.height) * VIEW_H;
    setCam((prev) => {
      const k = Math.min(Math.max(prev.k * factor, 0.4), 4);
      const scale = k / prev.k;
      return {
        k,
        x: px - (px - prev.x) * scale,
        y: py - (py - prev.y) * scale,
      };
    });
  };

  const fitToGraph = () => {
    const box = graphBounds(positions);
    if (!box) return;
    const k = Math.min(
      VIEW_W / Math.max(box.width, 1),
      VIEW_H / Math.max(box.height, 1),
      1.6,
    );
    setCam({
      k,
      x: VIEW_W / 2 - (box.x + box.width / 2) * k,
      y: VIEW_H / 2 - (box.y + box.height / 2) * k,
    });
  };

  const resetView = () => setCam({ k: 1, x: 0, y: 0 });

  // An edge whose endpoints are not both in the node set is not drawable. That
  // happens when the engine truncated the node list but kept the transfers, and
  // it is worth counting rather than silently dropping.
  //
  // `renderKey` is built from real transaction identity plus a per-duplicate
  // occurrence counter derived while walking the list. A bare array index would
  // not be stable across a change in what is drawable, and hash+endpoints alone
  // is not unique when a provider reports the same transfer twice.
  const { drawable, undrawable } = useMemo(() => {
    const seen = new Map();
    const kept = [];
    for (const e of edges) {
      if (!e.from_address || !e.to_address) continue;
      if (!positions.has(e.from_address) || !positions.has(e.to_address)) continue;
      const identity = `${e.transaction_hash ?? "edge"}-${e.from_address}-${e.to_address}`;
      const occurrence = seen.get(identity) ?? 0;
      seen.set(identity, occurrence + 1);
      kept.push({ edge: e, key: occurrence === 0 ? identity : `${identity}#${occurrence}` });
    }
    return { drawable: kept, undrawable: edges.length - kept.length };
  }, [edges, positions]);

  /*
   * How many transfers meet at each address, and what they add up to.
   *
   * A token contract or an exchange wallet can have dozens of edges meeting at
   * one node. Drawing a value label on each of those puts a dozen labels inside
   * the same few square centimetres, where they overlap into an unreadable
   * block -- which is exactly what a real hop-2 trace produced. Past
   * EDGE_LABEL_MAX the individual labels are replaced by a single aggregate on
   * the node, which is also the more useful reading: "12 transfers, 45,200
   * USDT" says something no individual edge label does.
   *
   * Only edges carrying a numeric amount are totalled. An edge with no amount
   * is a contract call that moved nothing, and counting it in "12 transfers"
   * while leaving it out of the total would read as an arithmetic error rather
   * than as the filter it is -- so the two counts are reported separately.
   */
  const hubs = useMemo(() => {
    const degree = new Map();
    for (const { edge } of drawable) {
      for (const side of ["from_address", "to_address"]) {
        const at = edge[side];
        if (!at) continue;
        degree.set(at, (degree.get(at) ?? 0) + 1);
      }
    }

    const totals = new Map();
    for (const { edge } of drawable) {
      for (const side of ["from_address", "to_address"]) {
        const at = edge[side];
        if (!at) continue;
        if (!totals.has(at)) totals.set(at, { counted: 0, byAsset: new Map() });
        const bucket = totals.get(at);
        if (typeof edge.amount === "number" && Number.isFinite(edge.amount)) {
          const asset = edge.asset || "?";
          bucket.counted += 1;
          bucket.byAsset.set(asset, (bucket.byAsset.get(asset) ?? 0) + edge.amount);
        }
      }
    }

    const aggregates = new Map();
    for (const [address, count] of degree) {
      if (count <= EDGE_LABEL_MAX) continue;
      const bucket = totals.get(address) || { counted: 0, byAsset: new Map() };
      aggregates.set(address, {
        edges: count,
        counted: bucket.counted,
        byAsset: bucket.byAsset,
      });
    }
    return { degree, aggregates };
  }, [drawable]);

  /*
   * Wheel is bound imperatively rather than through `onWheel` on the element.
   *
   * React attaches its wheel listener passively, so `event.preventDefault()` in
   * an `onWheel` handler is a no-op the browser logs as "Unable to
   * preventDefault inside passive event listener invocation" -- and, worse, the
   * page scrolls out from under the graph while the user is zooming it. An
   * explicitly non-passive native listener is the only way to claim the event.
   */
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (event) => {
      event.preventDefault();
      zoomAbout(event.clientX, event.clientY, event.deltaY < 0 ? 1.12 : 1 / 1.12);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // `zoomAbout` only reads refs and a functional setState, so re-binding on
    // every camera change is unnecessary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onBackgroundDown = (event) => {
    if (event.button !== 0) return;
    gesture.current = { kind: "pan", x: event.clientX, y: event.clientY, cam };
  };

  const onNodeDown = (event, address) => {
    if (event.button !== 0) return;
    // Stop the canvas from also starting a pan, so dragging a node moves the
    // node and dragging the background moves the camera. Never both.
    event.stopPropagation();
    const at = positions.get(address);
    if (!at) return;
    const point = toWorld(event, svgRef.current, cam);
    gesture.current = { kind: "node", address, dx: at.x - point.x, dy: at.y - point.y };
  };

  useEffect(() => {
    const move = (event) => {
      const g = gesture.current;
      if (!g) return;
      if (g.kind === "pan") {
        const el = svgRef.current;
        if (!el) return;
        const rect = el.getBoundingClientRect();
        setCam({
          k: g.cam.k,
          x: g.cam.x + ((event.clientX - g.x) / rect.width) * VIEW_W,
          y: g.cam.y + ((event.clientY - g.y) / rect.height) * VIEW_H,
        });
      } else {
        // Past a few pixels it is a drag, not a click, so selection is
        // suppressed on pointer up.
        g.moved = true;
        const point = toWorld(event, svgRef.current, cam);
        setDragged((prev) => ({
          ...prev,
          [g.address]: { x: point.x + g.dx, y: point.y + g.dy },
        }));
      }
    };
    const up = () => {
      gesture.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [cam]);

  useEffect(() => {
    fitToGraph();
    // Fit once per node set, not per camera change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laidOut.positions]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        <Button size="icon-sm" variant="outline" onClick={() => zoomAbout(...pointerCentre(svgRef.current), 1.25)} title="Zoom in" aria-label="Zoom in">
          <Plus className="size-3.5" />
        </Button>
        <Button size="icon-sm" variant="outline" onClick={() => zoomAbout(...pointerCentre(svgRef.current), 1 / 1.25)} title="Zoom out" aria-label="Zoom out">
          <Minus className="size-3.5" />
        </Button>
        <Button size="sm" variant="outline" onClick={fitToGraph}>
          Fit
        </Button>
        <Button size="sm" variant="outline" onClick={resetView}>
          Reset
        </Button>
        <span className="text-[10px] tabular-nums text-muted-foreground">
          {Math.round(cam.k * 100)}%
        </span>
      </div>

      <div className="relative overflow-hidden rounded-lg border bg-muted/20">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="h-[clamp(420px,58vh,820px)] w-full touch-none select-none"
          role="img"
          aria-label={`Fund flow between ${nodes.length} addresses and ${edges.length} transfers, laid out by hop distance from the subject. Drag to pan, scroll to zoom, drag a node to move it.`}
          onPointerDown={onBackgroundDown}
        >
        <g transform={`translate(${cam.x} ${cam.y}) scale(${cam.k})`}>
          <defs>
            <marker
              id="ff-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
            </marker>
            <marker
              id="ff-arrow-flag"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444" />
            </marker>
          </defs>

          {/* Hop columns, labelled. A column is a depth bucket, so the header
              is a claim the engine supports rather than a decoration. */}
          {Array.from(
            new Set(nodes.map((n) => n.depth || 0)),
          )
            .sort((a, b) => a - b)
            .map((depth) => {
              const positionsInLayer = nodes
                .filter((n) => (n.depth || 0) === depth)
                .map((n) => positions.get(n.address))
                .filter(Boolean);
              const x = positionsInLayer[0]?.x;
              if (x === undefined) return null;
              return (
                <text
                  key={depth}
                  x={x}
                  y={20}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[10px] font-semibold uppercase tracking-[0.16em]"
                >
                  {depth === 0 ? "Subject" : `Hop ${depth}`}
                </text>
              );
            })}

          {/* Edges */}
          {drawable.map(({ edge, key }) => {
            const from = positions.get(edge.from_address);
            const to = positions.get(edge.to_address);
            const flagged = (edge.risk_flags || []).length > 0;
            const mid = edgeMidpoint(from, to);
            const dimmed = hover && hover !== edge.from_address && hover !== edge.to_address;
            /*
             * A value label is drawn only while this edge is in focus.
             *
             * It used to be drawn always, at every edge midpoint, for every
             * edge. At one or two transfers that is a helpful annotation. At
             * 119 edges it is 119 overlapping strings in a band across the
             * middle of the canvas, which is not a chart any more -- it is a
             * grey smear with the occasional legible number in it, and the
             * numbers that survive are the ones nearest the front of the draw
             * order rather than the ones that matter.
             *
             * Focus is the edge under the pointer, or any edge touching the
             * hovered or clicked node. A node that is a hub suppresses its own
             * edges' labels in favour of the single aggregate, because the
             * aggregate is drawn at the node and the individual labels would
             * sit on top of it.
             */
            const touchesFocus = focusNode
              ? edge.from_address === focusNode || edge.to_address === focusNode
              : false;
            const isHub = Boolean(
              hubs.aggregates.get(edge.from_address) || hubs.aggregates.get(edge.to_address),
            );
            const showLabel =
              edge.amount !== null &&
              edge.amount !== undefined &&
              (edgeHover === key || (touchesFocus && !isHub));
            return (
              <g key={key}>
                <path
                  d={edgePath(from, to)}
                  fill="none"
                  stroke={flagged ? "#ef4444" : "#94a3b8"}
                  strokeWidth={flagged ? 1.8 : 1.1}
                  strokeOpacity={dimmed ? 0.12 : flagged ? 0.85 : 0.5}
                  markerEnd={
                    flagged ? "url(#ff-arrow-flag)" : "url(#ff-arrow)"
                  }
                  color={flagged ? "#ef4444" : "#94a3b8"}
                  onPointerEnter={() => setEdgeHover(key)}
                  onPointerLeave={() => setEdgeHover((k) => (k === key ? null : k))}
                >
                  <title>
                    {`${truncateHash(edge.from_address, 10, 8)} → ${truncateHash(edge.to_address, 10, 8)}\n${formatAmount(edge.amount, null, edge.asset)}\n${truncateHash(edge.transaction_hash, 12, 10)}${flagged ? `\nRisk flags: ${edge.risk_flags.join(", ")}` : ""}`}
                  </title>
                </path>
                {showLabel ? (
                  <text
                    x={mid.x}
                    y={mid.y}
                    textAnchor="middle"
                    className="fill-foreground text-[9px] font-medium"
                    paintOrder="stroke"
                    stroke="var(--background)"
                    strokeWidth="2.5"
                    strokeLinejoin="round"
                  >
                    {formatAmount(edge.amount, null, edge.asset)}
                  </text>
                ) : null}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const pos = positions.get(node.address);
            if (!pos) return null;
            const color = nodeColor(node);
            const r = nodeRadius(node);
            const dimmed =
              hover && hover !== node.address && !edges.some(
                (e) =>
                  (hover === e.from_address && e.to_address === node.address) ||
                  (hover === e.to_address && e.from_address === node.address),
              );
            return (
              <g
                key={node.address}
                transform={`translate(${pos.x} ${pos.y})`}
                opacity={dimmed ? 0.25 : 1}
                className="cursor-grab"
                onMouseEnter={() => setHover(node.address)}
                onMouseLeave={() => setHover(null)}
                onPointerUp={() => {
                  // Only a click without a drag is a selection. A node that was
                  // dragged into place should not also open the details panel.
                  if (gesture.current?.moved) return;
                  setPinned((p) => (p === node.address ? null : node.address));
                  onSelect?.(node);
                }}
                onPointerDown={(e) => onNodeDown(e, node.address)}
              >
                <circle
                  r={r}
                  fill={color}
                  fillOpacity={0.16}
                  stroke={color}
                  strokeWidth={node.is_seed ? 2.4 : 1.4}
                />
                {node.is_seed ? (
                  <circle r={r + 5} fill="none" stroke={color} strokeOpacity={0.3} strokeWidth={1} />
                ) : null}
                <text
                  y={r + 14}
                  textAnchor="middle"
                  className="fill-foreground text-[9px] font-mono"
                >
                  {truncateHash(node.address, 6, 4)}
                </text>
                <text
                  y={r + 25}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[8px]"
                >
                  {node.is_seed ? "subject" : entityTypeLabel(node.entity_type)}
                </text>
                {/*
                  The aggregate for a hub. Drawn under the node's own labels and
                  only while the node is in focus, so a busy address reads as one
                  number rather than as thirty.
                */}
                {(() => {
                  const agg = hubs.aggregates.get(node.address);
                  if (!agg || focusNode !== node.address) return null;
                  const noun = `${agg.edges} transfer${agg.edges === 1 ? "" : "s"}`;
                  /*
                   * Totals are per asset, never across assets.
                   *
                   * Summing a node's inbound and outbound flows into one number
                   * is meaningless when more than one asset is involved, and it
                   * is worse than meaningless because it looks like a real
                   * figure: 5.179 "USDT" assembled from part ETH, part WETH and
                   * part USDT is a number the reader will trust. So a single
                   * asset is totalled directly, and several assets are listed
                   * separately or not at all.
                   */
                  const assets = [...agg.byAsset.entries()].sort(
                    (a, b) => b[1] - a[1],
                  );
                  let detail;
                  if (assets.length === 1) {
                    detail = `, total ${formatAmount(assets[0][1], null, assets[0][0])}`;
                  } else if (assets.length > 1 && assets.length <= 3) {
                    detail = ` — ${assets
                      .map(([a, v]) => formatAmount(v, null, a))
                      .join(", ")}`;
                  } else if (assets.length > 3) {
                    detail = ` across ${assets.length} assets`;
                  } else {
                    detail = "";
                  }
                  const unpriced = agg.edges - agg.counted;
                  return (
                    <text
                      y={r + 36}
                      textAnchor="middle"
                      className="fill-foreground text-[9px] font-medium"
                      paintOrder="stroke"
                      stroke="var(--background)"
                      strokeWidth="2.5"
                      strokeLinejoin="round"
                    >
                      {`${noun}${detail}`}
                      {unpriced > 0
                        ? ` (${unpriced} with no recorded amount)`
                        : ""}
                    </text>
                  );
                })()}
                <title>
                  {`${node.address}\n${node.is_seed ? "Subject of this investigation" : entityTypeLabel(node.entity_type)}\n${node.inbound} in / ${node.outbound} out\nDepth ${node.depth}`}
                </title>
              </g>
            );
          })}
        </g>
        </svg>
      </div>

      {undrawable > 0 ? (
        <p className="text-xs text-muted-foreground">
          {undrawable} of {edges.length} transfers are not drawn because an
          endpoint address is outside the node set. They are listed in full in
          the transaction table below — the graph is a view, not the record.
        </p>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NODE DETAIL
// ---------------------------------------------------------------------------

export function NodeInspector({ node, chain, onClose }) {
  if (!node) return null;
  // Provider-supplied, so scheme-checked before it becomes an href. This is
  // the most clickable of the three citation links in the app: it sits inside
  // a graph node's tooltip, so a click here does not look like navigation to
  // the address and nothing about the surrounding UI says "this came from a
  // third party".
  const sourceUrl = safeSourceUrl(node.entity?.source_url);
  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">
              {node.is_seed ? "Subject address" : entityTypeLabel(node.entity_type)}
            </h4>
            {node.is_seed ? (
              <Badge variant="outline" className="border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                Trace seed
              </Badge>
            ) : null}
          </div>
          <p className="font-mono text-xs text-muted-foreground">{node.address}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        {[
          { label: "Depth", v: node.depth },
          { label: "Transfers in", v: node.inbound },
          { label: "Transfers out", v: node.outbound },
          {
            label: "Attribution",
            v: node.entity?.name ?? (node.entity_type && node.entity_type !== "unknown" ? entityTypeLabel(node.entity_type) : null),
          },
        ].map((item) => (
          <div key={item.label}>
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className="mt-0.5 font-medium">
              <Value>{item.v}</Value>
            </dd>
          </div>
        ))}
      </dl>

      {node.entity ? (
        <div className="mt-3 space-y-1.5 border-t pt-3 text-xs">
          <p className="font-medium">{node.entity.name}</p>
          {node.entity.source ? (
            <p className="text-muted-foreground">
              Source: {node.entity.source}
              {sourceUrl ? (
                <>
                  {" · "}
                  <a
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="underline underline-offset-2"
                  >
                    cited source
                  </a>
                </>
              ) : null}
            </p>
          ) : (
            <p className="text-muted-foreground">
              No source was recorded for this attribution, so it carries no
              weight as evidence of who controls the address.
            </p>
          )}
        </div>
      ) : null}

      {Array.isArray(node.evidence) && node.evidence.length ? (
        <ul className="mt-3 space-y-1.5 border-t pt-3">
          {node.evidence.map((e, i) => (
            <li key={i} className="text-xs leading-5 text-muted-foreground">
              {e}
            </li>
          ))}
        </ul>
      ) : null}

      <p className="mt-3 text-[10px] text-muted-foreground">
        Open the full address in the {chainLabel(chain)} explorer to verify
        anything shown here:{" "}
        <a
          href={
            node.address
              ? `https://${
                  { tron: "tronscan.org/#", ethereum: "etherscan.io", bsc: "bscscan.com", polygon: "polygonscan.com", bitcoin: "mempool.space" }[chain] ?? ""
                }/address/${encodeURIComponent(node.address)}`
              : undefined
          }
          target="_blank"
          rel="noreferrer noopener"
          className="underline underline-offset-2"
        >
          {truncateHash(node.address, 12, 8)}
        </a>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LEGEND
// ---------------------------------------------------------------------------

const LEGEND = [
  { type: "seed", label: "Subject", color: SUBJECT_COLOR, note: "The address this investigation started from." },
  { type: "mixer", label: "Mixer", color: ENTITY_COLOR.mixer, note: "A provider or curated label identifies this as a mixer." },
  { type: "sanctioned", label: "Sanctioned", color: ENTITY_COLOR.sanctioned, note: "Labelled as sanctioned by the source shown on the node." },
  { type: "exchange", label: "Exchange", color: ENTITY_COLOR.exchange, note: "Labelled as an exchange." },
  { type: "high_risk", label: "High risk", color: ENTITY_COLOR.high_risk, note: "Labelled as high risk." },
  { type: "unknown", label: "Unclassified", color: ENTITY_COLOR.unknown, note: "No attribution. This is not a clean address — it is an unattributed one." },
];

function GraphLegend() {
  return (
    <Disclosure label="Graph legend" hint="what the node colours mean" bodyClassName="text-xs">
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {LEGEND.map((item) => (
          <li key={item.type} className="flex items-start gap-2 text-xs">
            <span
              className="mt-1 size-2.5 shrink-0 rounded-full border-2"
              style={{ borderColor: item.color }}
              aria-hidden="true"
            />
            <span>
              <span className="font-medium">{item.label}</span>
              <span className="text-muted-foreground"> — {item.note}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
        Colour reflects the entity type attached to the address, not its risk
        score. A red line marks a transfer the risk engine flagged; the specific
        reasons are in the risk panel.
      </p>
    </Disclosure>
  );
}

// ---------------------------------------------------------------------------
// PUBLIC COMPONENT
// ---------------------------------------------------------------------------

export function FundFlowGraph({
  nodes = [],
  edges = [],
  transactions = [],
  chain = null,
  seed = null,
  /**
   * Lifts node selection out of the graph. When supplied, the graph reports the
   * selected node here and renders no inspector of its own, so the caller can put
   * the details in a drawer and leave the graph at full width. When omitted the
   * graph keeps its original inline inspector, which shrinks nothing but sits
   * under the canvas.
   */
  onSelectNode,
}) {
  const [mode, setMode] = useState("2d");
  const [selected, setSelected] = useState(null);

  const nodeList = useMemo(() => (Array.isArray(nodes) ? nodes : []), [nodes]);
  const edgeList = useMemo(() => (Array.isArray(edges) ? edges : []), [edges]);

  const select = (node) => {
    if (onSelectNode) {
      onSelectNode(node);
      return;
    }
    setSelected(node);
  };

  if (nodeList.length === 0) {
    return (
      <EmptyState
        icon={NetworkIcon}
        title="No addresses were established for this trace"
        description="The engine returned no address nodes. Check the outcome and the evidence notes above: an empty graph after a provider failure is a statement about the provider, and an empty graph because the subject genuinely has no history is a different finding entirely."
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/*
          The one place the graph states its own scale, and the one place it
          states its own controls. Both used to appear twice: the section
          description above the graph repeated the interaction help verbatim, and
          the SVG's aria-label carried a third copy for screen readers.
        */}
        <p className="text-xs text-muted-foreground">
          {nodeList.length} {nodeList.length === 1 ? "address" : "addresses"} ·{" "}
          {edgeList.length} {edgeList.length === 1 ? "transfer" : "transfers"} ·{" "}
          <span className="hidden sm:inline">
            {mode === "2d"
              ? "Drag to pan · Scroll to zoom · Drag nodes to reposition"
              : "Drag to rotate · Right-drag to pan · Scroll to zoom"}
          </span>
        </p>
        <div className="flex gap-1.5">
          <Button
            size="sm"
            variant={mode === "2d" ? "secondary" : "outline"}
            onClick={() => setMode("2d")}
          >
            <NetworkIcon className="size-3.5" />
            2D
          </Button>
          <Button
            size="sm"
            variant={mode === "3d" ? "secondary" : "outline"}
            onClick={() => setMode("3d")}
          >
            <Box className="size-3.5" />
            3D
          </Button>
        </div>
      </div>

      {mode === "2d" ? (
        <Graph2D nodes={nodeList} edges={edgeList} onSelect={select} />
      ) : (
        <Suspense
          fallback={
            <div className="flex h-[460px] items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
              Loading the 3D renderer…
            </div>
          }
        >
          <FundFlow3D nodes={nodeList} edges={edgeList} chain={chain} seed={seed} />
        </Suspense>
      )}

      {onSelectNode ? null : (
        <NodeInspector node={selected} chain={chain} onClose={() => setSelected(null)} />
      )}

      <GraphLegend />

      {transactions.length > 0 ? (
        <p className="text-[10px] text-muted-foreground">
          The graph is a view of {transactions.length} normalized{" "}
          {transactions.length === 1 ? "transaction" : "transactions"}. It shows
          what connects to the subject; the transaction table below is the
          complete record, including transfers whose counterparty is not in the
          node set.
        </p>
      ) : null}
    </div>
  );
}

export default FundFlowGraph;
