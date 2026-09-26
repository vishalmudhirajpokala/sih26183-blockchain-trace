/**
 * The landing page's ambient 3D scene.
 *
 * WHY AN IFRAME AND NOT THE SPLINE RUNTIME
 *
 * `@splinetool/react-spline` wants a published `.splinecode` file, addressed
 * like `https://prod.spline.design/<hash>/scene.splinecode`. This scene is
 * published in Spline's viewer format instead, which is the one Spline serves
 * for embedding and the one its own documentation hands you as an iframe
 * snippet. The two are not interchangeable: the runtime is pointed at a viewer
 * HTML page and cannot read it, and no `.splinecode` address is discoverable
 * from the viewer response.
 *
 * The iframe is also the better architecture here, for three reasons that are
 * worth the trade:
 *
 *   isolation        An error inside a nested browsing context cannot propagate
 *                    into this page. The runtime build needed an error boundary
 *                    precisely because it threw from inside React; an iframe
 *                    makes that class of failure structurally impossible.
 *   weight           The runtime is 34 MB unpacked and a 271 kB chunk, bundled
 *                    and versioned by us. Spline serves its own viewer from its
 *                    own CDN, so it is outside our dependency tree entirely.
 *   capability       The viewer deals with WebGL support, context loss and
 *                    resizing. We would be guessing at all three.
 *
 * To change the scene, paste a different viewer URL here. Nothing else to edit.
 */

/**
 * The published Spline viewer URL for the scene shown in the hero.
 *
 * This is a public address, not an `app.spline.design/file/...` editor link.
 * An editor link identifies a file inside one person's account and has no
 * public counterpart, so it cannot be embedded.
 */
export const HERO_SCENE_URL =
  "https://my.spline.design/cryptocoins-doKAgFLxDFsY8uRPqtpM6Km5/";

/**
 * Whether the scene should load at all.
 *
 * A continuous WebGL animation is suppressed outright -- not degraded -- for a
 * visitor whose system asks for reduced motion, because that preference is not
 * ours to overrule, and when no URL is configured, because there is then nothing
 * to show and reserving space for it would only shift the layout.
 */
export function heroSceneEnabled() {
  if (typeof window === "undefined") return false;
  if (!HERO_SCENE_URL) return false;

  try {
    return !window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  } catch {
    // matchMedia unavailable or blocked; allow the scene and let the viewer
    // decide what it can do.
    return true;
  }
}
