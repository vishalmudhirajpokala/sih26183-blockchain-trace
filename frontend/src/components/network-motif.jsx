/**
 * The hero's network motif -- a hand-built SVG, no library.
 *
 * WHY THIS EXISTS INSTEAD OF A 3D SCENE
 *
 * A hosted 3D viewer brings a vendor, an account, a watermark, a 34 MB runtime
 * or a cross-origin frame that paints its own opaque background, and a scene
 * that animates continuously against copy promising that everything shown is
 * real. None of that earns its place on this page. This is ~40 lines of SVG and
 * ~30 of CSS, ships in the CSS it already has, cannot fail to load, and costs
 * nothing when it is not wanted.
 *
 * WHAT IT IS, AND WHAT IT IS NOT
 *
 * It is decoration: a motif of a traced network, seven nodes and the edges
 * between them, with one node marked as the destination and a pulse running to
 * it. It carries no data -- no address, no amount, no timestamp, no label -- and
 * it is not generated from any trace. That matters here, because the landing
 * page's copy says everything shown is real, and a graph-shaped decoration is
 * the easiest thing on the page to misread as a real finding. It is
 * aria-hidden, it has no text in it, and every node is the same shape, so
 * nothing in it can be quoted as evidence.
 *
 * ONE DESTINATION, THE REST INTERMEDIATE
 *
 * The larger teal node with a breathing ring is the destination; the smaller
 * muted ones are intermediate wallets. The distinction is carried by size,
 * colour and the ring together, so it survives being read at a glance or in
 * greyscale, and it does not depend on colour alone.
 *
 * The pulse runs from a source node, along a path, to the destination, on a
 * five-second loop with a pause before it repeats. It uses `pathLength="100"`
 * so the dash arithmetic is a round number and does not depend on measuring
 * the path.
 *
 * Geometry is fixed rather than generated. A random layout would differ per
 * render, which is a layout shift on the one screen a judge sees first, and it
 * could not be reviewed.
 */

const NODES = [
  // x, y, r, kind: "source" | "hop" | "destination"
  { x: 46, y: 300, r: 5, kind: "source" },
  { x: 104, y: 232, r: 5, kind: "hop" },
  { x: 96, y: 356, r: 4, kind: "hop" },
  { x: 168, y: 268, r: 5, kind: "hop" },
  { x: 176, y: 366, r: 4, kind: "hop" },
  { x: 232, y: 214, r: 5, kind: "hop" },
  { x: 244, y: 320, r: 4, kind: "hop" },
  { x: 276, y: 262, r: 9, kind: "destination" },
];

const EDGES = [
  [0, 1], [0, 2], [1, 3], [2, 3], [2, 4], [3, 4],
  [3, 5], [3, 6], [4, 6], [5, 7], [6, 7],
];

// The traced path: source -> two hops -> destination. The pulse follows this
// one, so the animation reads as a single movement rather than as general
// activity everywhere at once.
const TRACED = [0, 3, 6, 7];

function tracedPath() {
  const pts = TRACED.map((i) => NODES[i]);
  return pts
    .map((p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`))
    .join(" ");
}

export function NetworkMotif({ className = "" }) {
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none select-none ${className}`}
    >
      <svg
        viewBox="0 0 320 400"
        className="h-full w-full"
        role="presentation"
        focusable="false"
      >
        <defs>
          <radialGradient id="bt-motif-dest" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#7fd6c6" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#4a9c92" stopOpacity="0.75" />
          </radialGradient>
        </defs>

        {/* Edges. Thin, low-contrast, and deliberately uneven in weight: the
            traced path is drawn slightly stronger so the pulse has something to
            travel along that the eye can follow. */}
        <g stroke="#3f6274" strokeWidth="1" fill="none" opacity="0.5">
          {EDGES.map(([a, b]) => {
            const onTraced =
              TRACED.includes(a) &&
              TRACED.includes(b) &&
              Math.abs(TRACED.indexOf(a) - TRACED.indexOf(b)) === 1;
            return (
              <line
                key={`${a}-${b}`}
                x1={NODES[a].x}
                y1={NODES[a].y}
                x2={NODES[b].x}
                y2={NODES[b].y}
                stroke={onTraced ? "#4e7c8e" : "#3f6274"}
                strokeWidth={onTraced ? 1.25 : 1}
                opacity={onTraced ? 0.75 : 0.45}
              />
            );
          })}
        </g>

        {/* The traced path, then the pulse travelling along it. Two strokes of
            the same path: a wide soft one for the glow and a narrow bright one
            for the signal. A blur filter would look marginally better and costs
            a full-frame filter pass on the page's first screen. */}
        <path
          d={tracedPath()}
          fill="none"
          stroke="#6fbfae"
          strokeWidth="4"
          strokeLinecap="round"
          pathLength="100"
          className="bt-motif-pulse-glow"
        />
        <path
          d={tracedPath()}
          fill="none"
          stroke="#a9e6da"
          strokeWidth="1.6"
          strokeLinecap="round"
          pathLength="100"
          className="bt-motif-pulse"
        />

        {/* Nodes. Same shape throughout so none of them can be read as carrying
            a value; the destination differs by size, colour and its ring. */}
        <g>
          {NODES.map((n, i) => {
            if (n.kind === "destination") return null;
            return (
              <circle
                key={i}
                cx={n.x}
                cy={n.y}
                r={n.r}
                fill={n.kind === "source" ? "#6d9fb5" : "#4b7f96"}
                fillOpacity="0.9"
              />
            );
          })}
        </g>

        {/* The destination: larger, teal, and with a ring that breathes. The
            ring is what makes it findable without relying on the fill colour
            being distinguishable. */}
        <circle
          cx={NODES[7].x}
          cy={NODES[7].y}
          r="16"
          fill="none"
          stroke="#5fb8a6"
          strokeWidth="1"
          className="bt-motif-ring"
        />
        <circle
          cx={NODES[7].x}
          cy={NODES[7].y}
          r={NODES[7].r}
          fill="url(#bt-motif-dest)"
        />
      </svg>
    </div>
  );
}
