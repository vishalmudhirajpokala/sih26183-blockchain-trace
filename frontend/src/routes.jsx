/**
 * The route table.
 *
 * Kept in one file, and in this order, for two reasons:
 *
 * 1. `site-header.jsx` reads `ROUTE_TITLES` from here so a page cannot exist
 *    without a name. A new route is one entry, and the breadcrumb updates with
 *    it.
 * 2. Reading the table top to bottom is how the product is meant to be walked:
 *    detect a chain, run a trace, read the graph, read the risk, read the
 *    report, then come back to the case.
 *
 * `/app/*` is the shell. Everything else is public: the landing page, and the
 * sign-in page (which must render *before* the access mode is known, since
 * determining the mode is what the guard does).
 */

import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { RequireAccess, RedirectIfSignedIn } from "@/components/route-guard";
import { LoadingBlock } from "@/components/common";
import Login from "@/pages/login";
import Landing from "@/pages/landing";

/**
 * Pages are split so the landing page does not ship the 3D graph renderer.
 * `@react-three/fiber` is the largest dependency in the app and only the
 * investigation detail page needs it.
 */
/*
 * `/app` renders the imported Dashboard 01 layout (`dashboard-01.jsx`), which
 * composes that block's `SectionCards` and `ChartAreaInteractive` against the
 * real analytics endpoints. The previous overview page is still on disk at
 * `pages/dashboard.jsx` and is not referenced by any route; it is kept as the
 * fallback for the older layout.
 */
const Dashboard = lazy(() => import("@/pages/dashboard-01"));
const TraceConsole = lazy(() => import("@/pages/trace-console"));
const Investigations = lazy(() => import("@/pages/investigations"));
const InvestigationDetail = lazy(() => import("@/pages/investigation-detail"));
const Reports = lazy(() => import("@/pages/reports"));
const Entities = lazy(() => import("@/pages/entities"));
const EntityDetail = lazy(() => import("@/pages/entity-detail"));
const RiskAnalytics = lazy(() => import("@/pages/risk-analytics"));
const NetworkExplorer = lazy(() => import("@/pages/network"));
const Help = lazy(() => import("@/pages/help"));
const NotFound = lazy(() => import("@/pages/not-found"));

/**
 * Section names, keyed by path. `site-header.jsx` renders these as the
 * breadcrumb leaf; dynamic segments (`/app/investigations/<id>`) inherit the
 * nearest named ancestor.
 */
export const ROUTE_TITLES = {
  "/app": "Dashboard",
  "/app/trace": "Trace Console",
  "/app/investigations": "Investigations",
  "/app/reports": "Reports",
  "/app/entities": "Entity Intelligence",
  "/app/risk": "Risk Analytics",
  "/app/network": "Network Explorer",
  "/app/help": "Help & Method",
};

/** A route boundary that shows why it is waiting rather than a blank frame. */
function PageFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="w-full max-w-md">
        <LoadingBlock label="Loading page" />
      </div>
    </div>
  );
}

export function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        {/* Public */}
        <Route path="/" element={<Landing />} />
        <Route
          path="/login"
          element={
            <RedirectIfSignedIn>
              <Login />
            </RedirectIfSignedIn>
          }
        />

        {/* The console. Everything under it needs a readable data source. */}
        <Route
          path="/app"
          element={
            <RequireAccess>
              <AppShell />
            </RequireAccess>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="trace" element={<TraceConsole />} />
          <Route path="investigations" element={<Investigations />} />
          <Route path="investigations/:id" element={<InvestigationDetail />} />
          <Route path="reports" element={<Reports />} />
          <Route path="entities" element={<Entities />} />
          <Route path="entities/:chain/:address" element={<EntityDetail />} />
          <Route path="risk" element={<RiskAnalytics />} />
          <Route path="network" element={<NetworkExplorer />} />
          <Route path="help" element={<Help />} />
        </Route>

        {/* `/trace` was the prototype's only page; send it to the real console
            rather than 404 so old bookmarks and screenshots still work. */}
        <Route path="/trace" element={<Navigate to="/app/trace" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}

export default App;
