import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * The one class-name builder.
 *
 * `clsx` flattens conditional class inputs (strings, arrays, objects) and
 * `twMerge` then resolves Tailwind conflicts so a caller can always override a
 * component's default without knowing which utility it used — passing
 * `className="w-32"` to a component that defaults to `w-full` wins, and
 * `className="p-2"` beats a default `p-6`, rather than both ending up in the
 * attribute and the winner depending on stylesheet order.
 *
 * This previously re-exported from a package literally named `cn`, which does
 * not exist; every `ui/*.jsx` imported that dead specifier and the component
 * layer could not resolve. `components.json` already declared this file as the
 * `utils` alias, so this is where it belonged.
 */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
