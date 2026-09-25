/**
 * The authenticated application shell: sidebar, header, and the routed page.
 *
 * This component owns exactly two responsibilities — the persistent chrome and
 * the outlet — so that every page is written once and rendered here. The
 * banner below it is the only place the deployment's access mode is announced,
 * because it is the one fact that changes the meaning of everything on screen.
 */

import { Link, Outlet } from "react-router-dom";
import { FlaskConicalIcon, ShieldAlertIcon, WifiOffIcon } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import {
  SidebarInset,
  SidebarProvider,
} from "@/components/ui/sidebar";
import { useAuth } from "@/hooks/use-auth";

/**
 * A standing statement about the deployment.
 *
 * RULE 6 — demo mode is clearly separated. In a demo, saved cases are in a
 * JSON file on one machine and everyone shares them, so the banner says so on
 * every page rather than only on the sign-in screen where it is easy to miss.
 */
function AccessBanner() {
  const { isDemo, status } = useAuth();
  if (!isDemo) return null;

  return (
    <div className="flex items-start gap-2 border-b border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200 lg:px-6">
      <FlaskConicalIcon className="mt-0.5 size-3.5 shrink-0" />
      <p>
        <strong className="font-semibold">Demo mode.</strong> No account is
        signed in. Cases are stored in a local JSON file and are visible to
        anyone using this deployment — do not enter real case data.
        {status?.note ? <span className="ml-1 opacity-80">{status.note}</span> : null}
      </p>
    </div>
  );
}

/** Shown when the API is down, on every page rather than only on first load. */
function OfflineBanner() {
  const { status, loading, refreshStatus } = useAuth();
  if (loading || status) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-red-300 bg-red-50 px-4 py-2 text-xs text-red-900 dark:border-red-900 dark:bg-red-950/60 dark:text-red-200 lg:px-6">
      <WifiOffIcon className="size-3.5 shrink-0" />
      <p className="flex-1">
        The BlockTrace API is not responding. Data on this page may be stale or
        absent, and no result below is a finding.
      </p>
      <button
        type="button"
        onClick={refreshStatus}
        className="font-semibold underline underline-offset-2"
      >
        Retry
      </button>
      <Link to="/app/help" className="underline underline-offset-2">
        Troubleshooting
      </Link>
      <span className="sr-only">
        <ShieldAlertIcon aria-hidden="true" />
      </span>
    </div>
  );
}

export function AppShell() {
  return (
    <SidebarProvider>
      <AppSidebar />
      {/*
        `@container/main` is what the Dashboard 01 components' container
        queries measure. `section-cards.jsx` and `data-table.jsx` size
        themselves with `@xl/main:` and `@5xl/main:`, but `ui/sidebar.jsx`
        renders `SidebarInset` as a bare `<main>` with no container type, so
        those queries never match and the stat row stays one column at every
        width. Declaring the container here — in BlockTrace's own shell, not in
        the shared primitive — is what makes the block's responsive behaviour
        work as designed.
      */}
      <SidebarInset className="@container/main">
        <AccessBanner />
        <OfflineBanner />
        <SiteHeader />
        <div className="flex flex-1 flex-col gap-6 p-4 md:p-6 lg:p-8">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
