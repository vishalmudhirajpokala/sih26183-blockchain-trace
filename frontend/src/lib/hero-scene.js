/**
 * The landing page's ambient 3D scene.
 *
 * WHY THE RUNTIME AND NOT AN IFRAME
 *
 * The first attempt embedded Spline's hosted viewer, because that was the URL
 * available at the time. It works, but it carries two costs that this URL does
 * not: the viewer paints its own body at an opaque
 * `rgba(34.05, 36.47, 46.15, 1)` and cannot be recoloured from a cross-origin
 * page, and it stamps a "Built with Spline" attribution over the scene.
 *
 * Given a published `.splinecode` file, the runtime renders the same scene with
 * no viewer chrome at all. That is the difference between a scene that has to be
 * disguised with a mask and one that simply sits on the page.
 *
 * To change the scene, export it from Spline (Export -> Spline file) and paste
 * the `https://prod.spline.design/<hash>/scene.splinecode` URL here.
 */

/**
 * The published scene file. This is the address the runtime loads; it is not an
 * `app.spline.design/file/...` editor link, which identifies a file inside one
 * person's account and has no public counterpart.
 */
export const HERO_SCENE_URL =
  "https://prod.spline.design/rHm9kW7Io6wrdQ5r/scene.splinecode";

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
    // matchMedia unavailable or blocked; allow the scene and let the runtime
    // decide what it can do.
    return true;
  }
}
