/**
 * The application header.
 *
 * The scaffold hard-coded the title "Documents" on every page, including the
 * trace console and the dashboard. A header that names the wrong section is
 * worse than no header: it tells the operator they are somewhere they are not.
 *
 * The title now comes from the route. Breadcrumbs are derived from the same
 * table, so a new page cannot forget to name itself.
 */

import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronRightIcon } from "lucide-react";

import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { ROUTE_TITLES } from "@/routes";

/**
 * The breadcrumb trail for the current path.
 *
 * Derived rather than stored on each page so a deep link that was never
 * navigated to â€” a bookmark, a shared URL â€” still gets a correct trail.
 */
function crumbsFor(pathname) {
  const segments = String(pathname || "")
    .split("/")
    .filter(Boolean);

  // `/app` is the shell, not a crumb.
  if (segments[0] === "app") segments.shift();

  const trail = [];
  let path = "/app";
  for (const segment of segments) {
    path += `/${segment}`;
    trail.push({
      to: path,
      // A dynamic segment (an investigation id, an address) has no title of its
      // own; the route table's section title stands in, and the id is rendered
      // truncated beside it.
      label: ROUTE_TITLES[path] || null,
      raw: segment,
    });
  }
  return trail;
}

export function SiteHeader() {
  const { pathname } = useLocation();
  const trail = crumbsFor(pathname);
  const leaf = trail[trail.length - 1];

  const title = leaf?.label || ROUTE_TITLES[pathname] || "BlockTrace";

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-(--header-height)">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator
          orientation="vertical"
          className="mx-2 h-4 data-vertical:self-auto"
        />

        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5">
          <Link
            to="/app"
            className="truncate text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            BlockTrace
          </Link>
          {trail.length > 0 ? (
            <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground/60" />
          ) : null}
          {trail.map((crumb, i) => {
            const isLast = i === trail.length - 1;
            return (
              <Fragment key={crumb.to}>
                {i > 0 ? (
                  <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground/60" />
                ) : null}
                {isLast || !crumb.label ? (
                  <span
                    className={`truncate text-sm ${isLast ? "font-medium" : "text-muted-foreground"}`}
                  >
                    {crumb.label || crumb.raw}
                  </span>
                ) : (
                  <Link
                    to={crumb.to}
                    className="truncate text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {crumb.label}
                  </Link>
                )}
              </Fragment>
            );
          })}
          {trail.length === 0 ? (
            <span className="truncate text-sm font-medium">{title}</span>
          ) : null}
        </nav>

        <ThemeToggle />
      </div>
    </header>
  );
}


