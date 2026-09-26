/**
 * The landing page's ambient 3D scene.
 *
 * WHY THIS IS A SEPARATE FILE WITH AN EMPTY DEFAULT
 *
 * A Spline scene is addressed by a *published* URL, which is a different thing
 * from the editor link. In the Spline app, press Export -> Code (or Share ->
 * Export) and copy the URL that looks like
 * `https://prod.spline.design/<hash>/scene.splinecode`. The file id from an
 * editor URL is not that URL, and constructing one from it yields a 403 from
 * Spline's CDN rather than a scene.
 *
 * So rather than hardcode a guess that would render a broken canvas on the
 * first thing a judge sees, the URL lives here, empty, and the hero renders
 * exactly as it did before until a real one is pasted in. Nothing about the
 * layout shifts when it is empty.
 */

/**
 * Paste the published scene URL here, or leave it empty to disable.
 *
 * The example shape is `https://prod.spline.design/<hash>/scene.splinecode`.
 */
export const HERO_SCENE_URL = "";

/**
 * Whether the scene should load at all.
 *
 * Two reasons to say no that are not about configuration:
 *
 *   `prefers-reduced-motion` -- this is a continuously moving WebGL canvas. A
 *   visitor who has asked their operating system to reduce motion gets a static
 *   page instead, which is the entire point of that setting and not a
 *   preference we are entitled to overrule.
 *
 *   no WebGL -- Spline needs a GPU context. On a machine without one the canvas
 *   is blank or throws, and a blank box in the hero reads as a broken site
 *   rather than a missing decoration.
 */
export function heroSceneEnabled() {
  if (typeof window === "undefined") return false;
  if (!HERO_SCENE_URL) return false;

  try {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return false;
  } catch {
    // matchMedia missing or blocked; treat as motion allowed and let the
    // WebGL check decide.
  }

  try {
    const canvas = document.createElement("canvas");
    const gl =
      canvas.getContext("webgl2") ||
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl");
    return Boolean(gl);
  } catch {
    return false;
  }
}
