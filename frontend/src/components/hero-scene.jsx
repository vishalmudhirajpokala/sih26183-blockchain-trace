import { useEffect, useState } from "react";

import { HERO_SCENE_URL, heroSceneEnabled } from "@/lib/hero-scene";

/**
 * Ambient 3D scene for the hero, as an isolated iframe.
 *
 * Three decisions worth stating, because each of them is a way this could have
 * gone wrong.
 *
 * IT IS LAZY, AND THE `src` IS THE THING THAT IS DEFERRED
 *
 * An iframe with a `src` in the first paint fetches and boots a WebGL viewer
 * while the headline is still trying to render. The element is rendered empty
 * and the `src` is attached only once the browser is idle, so the scene is in
 * the same code path as a below-the-fold image: present in the layout from the
 * start, loaded when it stops costing anything.
 *
 * IT IS NOT INTERACTIVE
 *
 * The canvas is decoration sitting in its own column, and an iframe that
 * captures pointer events would swallow a scroll gesture on a touch device and
 * could sit over the hero's own call to action. Non-interactive also means
 * nobody can drag a "graph" out of it and read it as data, which matters on a
 * page whose copy promises that everything shown is real.
 *
 * IT IS EXCLUDED FROM THE TAB ORDER AND FROM SCREEN READERS
 *
 * An iframe is focusable by default, so without `tabIndex={-1}` keyboard users
 * tab into an animation that does nothing. It also carries a `title`, because
 * that is what a frame is announced as, and the one it should be: decoration.
 */
export function HeroScene({ className = "" }) {
  const enabled = heroSceneEnabled();
  const [src, setSrc] = useState(null);

  useEffect(() => {
    if (!enabled || src) return undefined;
    const attach = () => setSrc(HERO_SCENE_URL);
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(attach, { timeout: 2500 });
      return () => window.cancelIdleCallback?.(handle);
    }
    const timer = window.setTimeout(attach, 500);
    return () => window.clearTimeout(timer);
  }, [enabled, src]);

  // Nothing configured: render nothing rather than an empty box, so the hero is
  // exactly the layout it would have been without this feature.
  if (!enabled) return null;

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      {/*
        The frame's own body is painted opaque -- `rgba(34.05, 36.47, 46.15, 1)`
        -- and it is cross-origin, so it cannot be recoloured from here. What can
        be changed is how its edges meet the page: without this the scene reads
        as a hard grey rectangle dropped onto the page, which is worse than no
        scene at all.

        So the frame is clipped to a large radius and feathered at the border.
        The feathering is deliberately shallow and the centre is left fully
        opaque, which keeps the subject of the animation crisp.

        It is also deliberately shallow at the bottom, where Spline's "Built
        with" attribution sits. Fading that corner out would be a way of hiding
        their attribution while claiming to be a visual effect, which is the one
        thing this is not here to do.
      */}
      <div
        className="h-full w-full overflow-hidden rounded-[2.5rem] [mask-image:linear-gradient(to_bottom,transparent_0,#000_9%,#000_86%,transparent_100%)]
        [-webkit-mask-image:linear-gradient(to_bottom,transparent_0,#000_9%,#000_86%,transparent_100%)]"
      >
        <iframe
          src={src || undefined}
          title="Decorative BlockTrace brand animation"
          tabIndex={-1}
          loading="lazy"
          referrerPolicy="no-referrer"
          className="h-full w-full border-0"
          allow="autoplay; fullscreen"
        />
      </div>
    </div>
  );
}
