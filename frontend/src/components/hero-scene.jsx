import { Component, Suspense, lazy, useEffect, useState } from "react";

import { HERO_SCENE_URL, heroSceneEnabled } from "@/lib/hero-scene";

/**
 * The Spline runtime is a WebGL runtime and it is not small -- 34 MB unpacked.
 * Loading it eagerly would put it in the entry bundle and make it compete with
 * the page for bandwidth on the one screen a judge sees first, for a decoration.
 *
 * So it is code-split and requested only once the browser is idle, and only when
 * a scene is actually configured. The build puts it in its own ~271 kB chunk
 * rather than the entry bundle.
 *
 * The default import is the plain runtime entry, not the `/next` one: that path
 * exists for Next.js server components and this is a Vite app.
 */
const Spline = lazy(() => import("@splinetool/react-spline"));

/**
 * Contains a scene that throws while running.
 *
 * This is not defensive padding; it is the thing that stops a decoration from
 * taking down a page. Tested by pointing the config at a URL that 403s: the
 * runtime throws "Data read, but end of buffer not reached" from inside the
 * component rather than rejecting the lazy import, so `Suspense` does not catch
 * it and the error propagates to the nearest boundary. There is no error
 * boundary anywhere else in this app, so without this one component the whole
 * landing page renders blank.
 *
 * Scene URLs also rot. Spline scenes are versioned, and an unpublished or
 * deleted scene starts failing with no change on our side at all. That failure
 * is expected rather than exceptional, and it has to be invisible.
 */
class SceneBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    // Intentionally silent. There is nothing useful to show a visitor about a
    // background animation failing, and the only reader is whoever already
    // knows: the URL in `lib/hero-scene.js` is wrong, or the scene is gone.
  }

  render() {
    if (this.state.failed) return null;
    return this.props.children;
  }
}

/**
 * Ambient 3D scene for the hero.
 *
 * Two decisions worth stating.
 *
 * IT IS LAZY, AND NOTHING IS REQUESTED UNTIL THE BROWSER IS IDLE
 *
 * The component is mounted immediately so the layout never shifts, but the
 * runtime chunk is only fetched once the browser has nothing better to do, so
 * the WebGL boot does not compete with the headline for the main thread.
 *
 * IT IS NOT INTERACTIVE
 *
 * The canvas is decoration in its own column. A canvas that captures pointer
 * events would swallow a scroll gesture on a touch device and could sit over
 * the hero's own call to action. Non-interactive also means nobody can drag a
 * "graph" out of it and read it as data, which matters on a page whose copy
 * promises that everything shown is real.
 *
 * There is no background colour on the container and no border-radius, because
 * the whole point of moving off the hosted viewer is that the scene no longer
 * arrives inside someone else's painted box. If a visible rectangle still
 * appears, it is the background colour set on the scene itself in Spline --
 * something only the scene's author can change.
 */
export function HeroScene({ className = "" }) {
  const enabled = heroSceneEnabled();
  const [requested, setRequested] = useState(false);

  useEffect(() => {
    if (!enabled || requested) return undefined;
    const attach = () => setRequested(true);
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(attach, { timeout: 2500 });
      return () => window.cancelIdleCallback?.(handle);
    }
    const timer = window.setTimeout(attach, 400);
    return () => window.clearTimeout(timer);
  }, [enabled, requested]);

  // Nothing configured: render nothing rather than an empty box, so the hero is
  // exactly the layout it would have been without this feature.
  if (!enabled || !requested) return null;

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      <SceneBoundary>
        <Suspense fallback={null}>
          <Spline scene={HERO_SCENE_URL} />
        </Suspense>
      </SceneBoundary>
    </div>
  );
}
