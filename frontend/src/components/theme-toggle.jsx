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
 * Dark is the default. A first-time visitor gets the dark theme regardless of
 * what their operating system asks for, because this is a console people sit in
 * for long stretches and the dark surface is the one it is designed around. The
 * system preference is deliberately not consulted: an operator who has chosen
 * light should not have it flip at sunset, and one who has chosen nothing should
 * not be moved by a setting they never touched.
 *
 * The only value that means "go light" is an explicit stored `"light"`, so
 * "no stored choice" and "chose dark" are the same state and need no flag of
 * their own.
 *
 * Two details this gets right:
 *
 * 1. **The class is applied before first paint** by a small inline script in
 *    `index.html`, not from here. React mounting after the stylesheet has
 *    already painted would show a white flash to every first-time visitor.
 *    This component only takes over once React is running.
 *
 * 2. **The icon says which mode it switches to**, not which one is active: a
 *    moon while dark, a sun while light. It is labelled for screen readers too,
 *    because the icon is the one place a control here is ambiguous. It is a real
 *    `<button>` from `ui/button`, so it is reachable by keyboard and toggles on
 *    Enter/Space without extra wiring.
 */

import { useCallback, useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

/** Shared with the pre-paint script in `index.html`; both must agree. */
const STORAGE_KEY = "blocktrace.theme";

/** Only an explicit `"light"` means light. Everything else is dark. */
function prefersLight() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "light";
  } catch {
    // Private-browsing quota failures must not stop the page rendering, and a
    // missing choice is not a request for the light theme.
    return false;
  }
}

export function ThemeToggle() {
  const [isDark, setIsDark] = useState(() => !prefersLight());

  // Keep the document in step with the state, including on first mount, so the
  // class the pre-paint script set is confirmed rather than assumed.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

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

  const label = isDark ? "Switch to light theme" : "Switch to dark theme";

  return (
    <Button
      variant="ghost"
      size="icon"
      className="ml-auto size-8"
      onClick={toggle}
      title={label}
    >
      {isDark ? <SunIcon /> : <MoonIcon />}
      <span className="sr-only">{label}</span>
    </Button>
  );
}
