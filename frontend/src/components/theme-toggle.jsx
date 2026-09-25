/**
 * Light / dark switch.
 *
 * The base-nova theme is class-driven: `@custom-variant dark (&:is(.dark *))`
 * in `index.css` makes every `dark:` utility in the Dashboard 01 components
 * respond to a `.dark` class on `<html>`, and the `.dark` block redefines
 * `--background`, `--card`, `--sidebar`, `--primary` and the rest. So switching
 * themes is one class on one element — no component needs to know about it, and
 * every page follows at once.
 *
 * Three details that this gets right:
 *
 * 1. **The class is applied before first paint** by a small inline script in
 *    `index.html`, not from here. React mounting after the stylesheet has
 *    already painted would show a white flash to anyone whose theme is dark.
 *    This component only takes over once React is running.
 *
 * 2. **First visit follows the operating system.** A stored choice wins; with
 *    no stored choice the `prefers-color-scheme` query decides. The choice is
 *    then written to `localStorage` so the next visit is not re-asked.
 *
 * 3. **The button says which mode it switches to**, and is labelled for screen
 *    readers, because the icon alone is the one place a control here is
 *    ambiguous. It is a real `<button>` from `ui/button`, so it is reachable by
 *    keyboard and toggles on Enter/Space without extra wiring.
 */

import { useCallback, useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

/** Shared with the pre-paint script in `index.html`; both must agree. */
const STORAGE_KEY = "blocktrace.theme";

/** The system's preference, or light where the query is unsupported. */
function systemPrefersDark() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readStoredTheme() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private-browsing quota failures must not stop the page rendering.
    return null;
  }
}

export function ThemeToggle() {
  const [isDark, setIsDark] = useState(() => {
    const stored = readStoredTheme();
    if (stored === "dark" || stored === "light") return stored === "dark";
    return systemPrefersDark();
  });

  // Keep the document in step with the state, including on first mount, so the
  // class the pre-paint script set is confirmed rather than assumed.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

  // A stored choice is a decision, not a preference: once the operator has
  // chosen, a later change to the OS theme should not override it.
  useEffect(() => {
    if (readStoredTheme()) return undefined;
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return undefined;

    const onChange = (event) => setIsDark(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    setIsDark((previous) => {
      const next = !previous;
      document.documentElement.classList.toggle("dark", next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
      } catch {
        /* the theme still switches for this session */
      }
      return next;
    });
  }, []);

  return (
    <Button
      variant="ghost"
      size="icon"
      className="ml-auto size-8"
      onClick={toggle}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
      <span className="sr-only">
        {isDark ? "Switch to light theme" : "Switch to dark theme"}
      </span>
    </Button>
  );
}
