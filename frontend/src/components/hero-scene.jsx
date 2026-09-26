import { Component, Suspense, lazy, useEffect, useState } from "react";

import { HERO_SCENE_URL, heroSceneEnabled } from "@/lib/hero-scene";

/**
 * The Spline runtime is a WebGL runtime and it is not small. Loading it eagerly
 * would put it in the entry bundle and make it compete with the page for
 * bandwidth on the one screen a judge sees first -- for a decoration.
 *
 * So it is code-split and requested only once the browser is idle, and only
 * when the scene is actually going to be shown. If the chunk fails to arrive,
 * the Suspense fallback is simply what remains and the hero is unchanged.
 */
const Spline = lazy(() => import("@splinetool/react-spline"));

/**
 * Contains a scene that throws while running.
 *
 * This is not defensive padding; it is the thing that stops a decoration from
 * taking down a page. Tested by pointing the config at a URL that returns 403:
 * the Spline runtime then fails *inside* the component -- "Data read, but end of
 * buffer not reached" -- rather than rejecting the lazy import, so `Suspense`
 * does not catch it and the error propagates to the nearest boundary. There is
 * no boundary anywhere else in this app, so without this one component the whole
 * landing page renders blank.
 *
 * Scene URLs also rot. Spline scenes are versioned, and an unpublished or
 * deleted scene starts 403ing with no change on our side at all. That failure is
 * expected rather than exceptional, and it has to be invisible.
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
 * Deliberately non-interactive and hidden from assistive technology, because it
 * carries no information -- it is decoration -- and three specific risks come
 * from forgetting that:
 *
 *   pointer events  a canvas that swallows clicks sits over the hero's own call
 *                   to action, and on a touch device it can swallow a scroll.
 *   aria-hidden     a decorative graphic announced as content is noise at best
 *                   and misleading at worst.
 *   motion          continuous animation, which is why a reduced-motion
 *                   preference and a missing GPU each suppress the scene
 *                   outright rather than degrading it quietly.
 */
export function HeroScene({ className = "" }) {
  const enabled = heroSceneEnabled();
  const [requested, setRequested] = useState(false);

  useEffect(() => {
    if (!enabled || requested) return undefined;
    const run = () => setRequested(true);
    // requestIdleCallback where available; a short timeout otherwise, so the
    // scene still appears on browsers without it rather than never appearing.
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(run, { timeout: 2000 });
      return () => window.cancelIdleCallback?.(handle);
    }
    const timer = window.setTimeout(run, 400);
    return () => window.clearTimeout(timer);
  }, [enabled, requested]);

  // Nothing to show. Returning null rather than an empty box keeps the hero
  // pixel-identical to its pre-scene form, so the page does not reserve space
  // for something that is not there.
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
