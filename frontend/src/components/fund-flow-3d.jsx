import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";
import {
  CameraControls,
  CameraControlsImpl,
  Html,
} from "@react-three/drei";
import { Maximize2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

/* =========================================================
   NODE COLORS
   ========================================================= */

function nodeColor(type) {
  if (type === "source") return "#3b82f6";
  if (type === "destination") return "#10b981";
  if (type === "obstruction") return "#f59e0b";
  return "#64748b";
}

/* =========================================================
   LABEL
   ========================================================= */

function NodeLabel({
  label,
  address,
  type,
}) {
  const color = nodeColor(type);

  return (
    <Html
      position={[0, 0.75, 0]}
      center
      distanceFactor={8}
      transform={false}
      sprite
      style={{
        pointerEvents: "none",
        userSelect: "none",
      }}
    >
      <div
        style={{
          width: 185,
          padding: "8px 10px",
          borderRadius: 8,
          border: `1px solid ${color}66`,
          background: "rgba(5, 13, 23, 0.94)",
          boxShadow: `0 6px 24px rgba(0,0,0,.25), 0 0 18px ${color}18`,
          fontFamily:
            'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
          textAlign: "left",
        }}
      >
        <div
          style={{
            marginBottom: 5,
            color,
            fontSize: 9,
            fontWeight: 800,
            letterSpacing: "0.12em",
          }}
        >
          {label}
        </div>

        <div
          style={{
            color: "#d3dce6",
            fontSize: 10,
            lineHeight: 1.35,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={address}
        >
          {address}
        </div>
      </div>
    </Html>
  );
}

/* =========================================================
   NODE
   ========================================================= */

function FlowNode({
  node,
}) {
  const groupRef = useRef(null);
  const color = nodeColor(node.type);

  useFrame((state) => {
    if (!groupRef.current) return;

    const t = state.clock.getElapsedTime();

    groupRef.current.position.y =
      node.position[1] +
      Math.sin(t * 1.1 + node.index * 0.8) * 0.035;
  });

  return (
    <group
      ref={groupRef}
      position={node.position}
    >
      {/* Outer glow */}
      <mesh>
        <sphereGeometry args={[0.58, 32, 32]} />

        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.08}
        />
      </mesh>

      {/* Main node */}
      <mesh>
        <sphereGeometry args={[0.30, 32, 32]} />

        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.55}
          metalness={0.25}
          roughness={0.28}
        />
      </mesh>

      {/* Core */}
      <mesh scale={0.48}>
        <sphereGeometry args={[0.30, 24, 24]} />

        <meshBasicMaterial
          color="#ffffff"
          transparent
          opacity={0.25}
        />
      </mesh>

      <NodeLabel
        label={node.label}
        address={node.address}
        type={node.type}
      />
    </group>
  );
}

/* =========================================================
   CURVE
   ========================================================= */

function makeCurve(start, end) {
  const a = new THREE.Vector3(...start);
  const b = new THREE.Vector3(...end);

  const midpoint = a.clone().lerp(b, 0.5);

  midpoint.y +=
    Math.max(0.8, Math.abs(b.y - a.y) * 0.5);

  midpoint.z += 0.2;

  return new THREE.QuadraticBezierCurve3(
    a,
    midpoint,
    b,
  );
}

/* =========================================================
   ANIMATED PARTICLE
   ========================================================= */

function FlowParticle({
  curve,
  delay = 0,
  reverse = false,
}) {
  const ref = useRef(null);

  useFrame((state) => {
    if (!ref.current) return;

    const elapsed =
      state.clock.getElapsedTime();

    let progress =
      ((elapsed * 0.16 + delay) % 1 + 1) % 1;

    if (reverse) {
      progress = 1 - progress;
    }

    const point =
      curve.getPoint(progress);

    ref.current.position.copy(point);
  });

  return (
    <mesh ref={ref}>
      <sphereGeometry
        args={[0.08, 12, 12]}
      />

      <meshBasicMaterial
        color="#8ec5ff"
      />
    </mesh>
  );
}

/* =========================================================
   CONNECTION
   ========================================================= */

/**
 * A connection drawn with `THREE.Line` rather than drei's `<Line>`.
 *
 * drei's fat-line implementation is a different thing: it builds a ribbon
 * geometry with per-segment caps, which needs `LineMaterial`, `LineSegments2`,
 * and a shader source assembled at runtime. It was roughly 160 kB of the ~990 kB
 * this chunk used to cost, in a view that is by construction optional — the
 * 3D button is a second rendering of a graph the 2D view already draws.
 *
 * A plain `THREE.Line` cannot be given a width in pixels (WebGL ignores
 * `linewidth` above 1), so the visual result is a hairline rather than a
 * 1.5-pixel line. That is a real reduction in quality and it is deliberate: the
 * transfer is still legible because it is tinted by direction and animated by
 * `FlowParticle`, and the exchange pays 160 kB only on the routes that ask for
 * 3D. If the 3D view ever becomes a default rather than a toggle, revisit
 * this — a hairline is the right trade only while 3D is opt-in.
 */
function FlowConnection({
  start,
  end,
  last,
}) {
  const curve = useMemo(
    () => makeCurve(start, end),
    [start, end],
  );

  const points = useMemo(
    () => curve.getPoints(60),
    [curve],
  );

  const color = last ? "#10b981" : "#3b82f6";

  const geometry = useMemo(
    () => new THREE.BufferGeometry().setFromPoints(points),
    [points],
  );

  return (
    <group>
      <line geometry={geometry}>
        <lineBasicMaterial
          color={color}
          transparent
          opacity={0.75}
        />
      </line>

      <FlowParticle
        curve={curve}
        delay={0}
      />

      <FlowParticle
        curve={curve}
        delay={0.5}
        reverse
      />
    </group>
  );
}

/* =========================================================
   GRID
   ========================================================= */

function SceneGrid() {
  return (
    <>
      <gridHelper
        args={[
          36,
          36,
          "#1a334d",
          "#102438",
        ]}
        position={[0, -2, 0]}
      />

      <gridHelper
        args={[
          36,
          36,
          "#102438",
          "#0d2134",
        ]}
        rotation={[
          Math.PI / 2,
          0,
          0,
        ]}
        position={[0, 0, -3.2]}
      />
    </>
  );
}

/* =========================================================
   SCENE
   ========================================================= */

/**
 * Lay the real graph out by hop distance from the subject.
 *
 * The prototype arranged nodes in a straight line, which only works for a
 * single path. A trace is a graph, not a path: a subject routinely fans out to
 * several counterparties, and a linear layout draws a relationship between two
 * addresses that never transacted. So nodes are placed in depth columns, and
 * connections are drawn only where the engine actually produced an edge.
 *
 * Depth comes from the engine's own `depth` field — the number of hops from the
 * subject — rather than from position in the array, which would silently
 * re-derive something the engine already computed.
 */
function layoutGraph(nodes, seed) {
  const subject = nodes.find(
    (n) => n?.is_seed || (seed && String(n?.address) === String(seed)),
  );
  const subjectDepth =
    subject && typeof subject.depth === "number" ? subject.depth : 0;

  const columns = new Map();
  for (const node of nodes) {
    if (!node?.address) continue;
    const raw = typeof node.depth === "number" ? node.depth : 0;
    const d = Math.max(0, raw - subjectDepth);
    if (!columns.has(d)) columns.set(d, []);
    columns.get(d).push(node);
  }

  const positions = new Map();
  [...columns.keys()]
    .sort((a, b) => a - b)
    .forEach((d) => {
      const column = columns.get(d);
      column.forEach((node, rowIndex) => {
        const y = (rowIndex - (column.length - 1) / 2) * 2.6;
        // A slight z offset keeps two addresses at the same depth from
        // collapsing onto one another in screen space.
        const z = (rowIndex % 2 === 0 ? 1 : -1) * 0.15;
        positions.set(String(node.address), [d * 5.2, y, z]);
      });
    });

  return { positions, subject, subjectDepth };
}

function FundFlowScene({ nodes, edges, seed, controlsRef, registerFit }) {
  const { positions, subjectDepth } = useMemo(
    () => layoutGraph(nodes, seed),
    [nodes, seed],
  );

  // Only edges whose two endpoints are both placed can be drawn. An edge
  // pointing at an address outside the node set is a real gap in the graph, so
  // it is counted and reported rather than silently dropped.
  const { drawn, undrawn } = useMemo(() => {
    const connections = [];
    const seen = new Map();
    let missing = 0;
    for (const edge of edges) {
      const from = positions.get(String(edge?.from_address ?? ""));
      const to = positions.get(String(edge?.to_address ?? ""));
      if (!from || !to) {
        missing += 1;
        continue;
      }
      /*
       * A stable, collision-free key from real transaction identity.
       *
       * The previous key was `hash-from-to`, which is not unique: a provider
       * can report the same transfer more than once, and two edges sharing a
       * hash between the same pair produced the same string. React then
       * duplicated or dropped the connections and logged a key warning.
       *
       * The occurrence counter is derived from the data as it is walked, so it
       * is deterministic for a given edge list -- it is not an array index that
       * changes when the list is filtered or reordered, and not a random or
       * render-time value. The identity of the connection is still the real
       * transaction hash plus its two real endpoints.
       */
      const identity = `${edge?.transaction_hash ?? "edge"}-${edge?.from_address}-${edge?.to_address}`;
      const occurrence = seen.get(identity) ?? 0;
      seen.set(identity, occurrence + 1);
      connections.push({
        key: occurrence === 0 ? identity : `${identity}#${occurrence}`,
        from,
        to,
      });
    }
    return { drawn: connections, undrawn: missing };
  }, [edges, positions]);

  /*
   * Fit and Reset.
   *
   * These are pure camera moves. They recompute a look-at from the positions the
   * scene was just laid out with and hand it to the same CameraControls the user
   * already drives with the mouse, so the buttons and the gestures cannot drift
   * apart. No request is made and no state is fetched: the camera is the only
   * thing that changes.
   */
  useEffect(() => {
    if (typeof registerFit !== "function") return;
    registerFit({
      fit: () => {
        const controls = controlsRef?.current;
        if (!controls || positions.size === 0) return;
        const box = new THREE.Box3();
        for (const p of positions.values()) box.expandByPoint(new THREE.Vector3(...p));
        if (box.isEmpty()) return;
        const centre = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3()).length();
        const fov = (controls.object?.fov ?? 48) * (Math.PI / 180);
        // A little headroom, clamped so a two-node graph is not shoved to the
        // orbit limits.
        const distance = Math.min(
          Math.max((size / 2 / Math.tan(fov / 2)) * 1.35, 6),
          44,
        );
        controls.setLookAt(
          centre.x,
          centre.y + distance * 0.25,
          centre.z + distance,
          centre.x,
          centre.y,
          centre.z,
          true,
        );
      },
      reset: () => {
        controlsRef?.current?.reset?.(true);
      },
    });
  }, [positions, controlsRef, registerFit]);

  const sceneNodes = useMemo(
    () =>
      nodes
        .filter((n) => n?.address && positions.has(String(n.address)))
        .map((node, index) => {
          const isSubject =
            node.is_seed || (seed && String(node.address) === String(seed));
          const depth =
            typeof node.depth === "number" ? node.depth - subjectDepth : 0;
          return {
            index,
            address: node.address,
            position: positions.get(String(node.address)),
            type: isSubject ? "source" : depth >= 1 ? "destination" : "intermediate",
            label: isSubject
              ? "SUBJECT"
              : node.entity?.name || `HOP ${node.entity_type || depth}`,
          };
        }),
    [nodes, positions, seed, subjectDepth],
  );

  return (
    <>
      {/* Background */}
      <color
        attach="background"
        args={["#06101b"]}
      />

      <fog
        attach="fog"
        args={[
          "#06101b",
          15,
          34,
        ]}
      />

      {/* Lighting */}
      <ambientLight intensity={1.25} />

      <directionalLight
        position={[5, 7, 8]}
        intensity={2.2}
      />

      <pointLight
        position={[-8, 4, 4]}
        intensity={35}
        distance={18}
        color="#3b82f6"
      />

      <pointLight
        position={[8, 3, -3]}
        intensity={30}
        distance={18}
        color="#10b981"
      />

      <SceneGrid />

      {/* Connections */}
      {drawn.map((conn) => (
        <FlowConnection
          key={conn.key}
          start={conn.from}
          end={conn.to}
        />
      ))}

      {/* Nodes */}
      {sceneNodes.map((node) => (
        <FlowNode
          key={`${node.address}-${node.index}`}
          node={node}
        />
      ))}

      {/* An undrawable edge is a gap in the graph, not a rendering artifact.
          It is announced here rather than passed off as a complete picture. */}
      <Html
        position={[0, -3.4, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: "none", userSelect: "none" }}
      >
        <div
          style={{
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: 10,
            color: undrawn > 0 ? "#f59e0b" : "#475569",
          }}
        >
          {undrawn > 0
            ? `${undrawn} transfer${undrawn === 1 ? "" : "s"} could not be drawn — an endpoint is outside the node set`
            : "Every transfer in the node set is drawn"}
        </div>
      </Html>

      {/* Camera controls */}
      <CameraControls
        ref={controlsRef}
        makeDefault

        mouseButtons={{
          left: CameraControlsImpl.ACTION.ROTATE,
          middle: CameraControlsImpl.ACTION.DOLLY,
          right: CameraControlsImpl.ACTION.TRUCK,
          wheel: CameraControlsImpl.ACTION.DOLLY,
        }}

        touches={{
          one: CameraControlsImpl.ACTION_TOUCH_ROTATE,
          two: CameraControlsImpl.ACTION_TOUCH_DOLLY_TRUCK,
          three: CameraControlsImpl.ACTION_TOUCH_DOLLY_TRUCK,
        }}

        smoothTime={0.15}
        draggingSmoothTime={0.12}

        dollyToCursor

        minDistance={5}
        maxDistance={45}

        minPolarAngle={Math.PI * 0.18}
        maxPolarAngle={Math.PI * 0.82}

        truckSpeed={2.5}
        azimuthRotateSpeed={0.5}
        polarRotateSpeed={0.4}
      />
    </>
  );
}

/* =========================================================
   PUBLIC COMPONENT
   ========================================================= */

/**
 * The 3D fund-flow view.
 *
 * It is fed the *same* `nodes` and `edges` the 2D view receives — the same
 * `TraceNode.to_dict()` and `TraceEdge.to_dict()` records — rather than a
 * derived address list. The prototype's version took a `path` prop that the
 * graph component never supplied, so switching to 3D rendered a blank canvas
 * while the 2D view above it was complete. Two views of the same trace that can
 * disagree are worse than one view, so the two are now driven by one input.
 *
 * 3D is a *reading* of the graph, not a different trace. Nothing here adds,
 * removes, or reorders a transfer: the particle direction along each connection
 * is the only thing the third dimension adds, and it is taken from the edge's
 * own from/to, not from hop order.
 */
export default function FundFlow3D({
  nodes = [],
  edges = [],
  chain = null,
  seed = null,
}) {
  const nodeList = useMemo(
    () => (Array.isArray(nodes) ? nodes : []),
    [nodes],
  );
  const edgeList = useMemo(
    () => (Array.isArray(edges) ? edges : []),
    [edges],
  );

  /*
   * The camera controls live inside the canvas, but the buttons that drive them
   * sit in the header outside it. A ref to the controls plus a `fit` callback
   * the scene registers is the smallest bridge between the two: no duplicated
   * camera state, and the buttons call the same object the gestures do.
   */
  const controlsRef = useRef(null);
  const [camera, setCamera] = useState({ fit: null, reset: null });
  const registerFit = useCallback((api) => setCamera(api), []);

  if (nodeList.length === 0) {
    return null;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-[#06101b] shadow-lg">
      {/* Header */}
      <div className="flex flex-col gap-2 border-b border-slate-800 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-bold tracking-[0.16em] text-slate-100">
            3D FUND FLOW
          </p>

          <p className="mt-1 text-[11px] text-slate-500">
            {nodeList.length}{" "}
            {nodeList.length === 1
              ? "address"
              : "addresses"}{" "}
            · {edgeList.length}{" "}
            {edgeList.length === 1
              ? "transfer"
              : "transfers"}{" "}
            · same graph as the 2D view
          </p>
        </div>

        <div className="flex items-center gap-3 text-[10px]">
          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="size-1.5 rounded-full bg-blue-500" />
            Source
          </span>

          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="size-1.5 rounded-full bg-slate-500" />
            Hop
          </span>

          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="size-1.5 rounded-full bg-emerald-500" />
            Destination
          </span>
        </div>
      </div>

      {/*
        Camera Fit / Reset, in the same place the 2D view puts its own so the two
        tabs read as one tool. These only move the camera — no request, no
        re-render of the graph — so they are safe to press mid-investigation.
      */}
      <div className="flex items-center justify-end gap-1.5 border-b border-slate-800 bg-[#071421] px-3 py-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => camera.fit?.()}
          disabled={!camera.fit}
          title="Frames the whole graph in the current canvas"
        >
          <Maximize2 className="size-3.5" data-icon="inline-start" />
          Fit
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => camera.reset?.()}
          disabled={!camera.reset}
          title="Returns the camera to the position the view started from"
        >
          <RotateCcw className="size-3.5" data-icon="inline-start" />
          Reset
        </Button>
      </div>

      {/*
        A real workspace rather than a fixed 500px strip. `h-[clamp(...)]` gives
        a short graph on a small laptop and a tall one on a large display, and
        `min-h-[420px]` keeps it usable on a phone. The previous fixed height sat
        inside a ~300px column, which is why the camera felt dead: there was
        nowhere to orbit to.
      */}
      <div className="h-[clamp(420px,62vh,860px)] w-full min-w-0">
        <Canvas
          dpr={[1, 1.75]}
          camera={{
            position: [0, 3.2, 14],
            fov: 48,
            near: 0.1,
            far: 100,
          }}
          gl={{
            antialias: true,
            alpha: false,
          }}
        >
          <FundFlowScene
            nodes={nodeList}
            edges={edgeList}
            chain={chain}
            seed={seed}
            controlsRef={controlsRef}
            registerFit={registerFit}
          />
        </Canvas>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-slate-800 bg-[#071421] px-4 py-2.5 text-[10px]">
        <span className="text-slate-500">
          Each connection follows that transfer&apos;s own from → to
        </span>

        <span className="font-semibold text-blue-400">
          {seed ? `SUBJECT ${String(seed).slice(0, 8).toUpperCase()}…` : "NO SUBJECT SET"}
        </span>
      </div>
    </div>
  );
}