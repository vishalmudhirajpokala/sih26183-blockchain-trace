/**
 * The application sidebar.
 *
 * Two things were wrong with the scaffold and both are RULE 5 violations:
 *
 * 1. Every nav item pointed at `#`.
 * 2. The footer read "TRON NETWORK / Mainnet Â· Live data" with a green dot,
 *    hard-coded. It was not a measurement of anything. It was a decoration
 *    asserting that a live multi-chain tool was connected to one specific
 *    network, which is both false (it is multi-chain) and unfalsifiable (it
 *    could never notice the API going down).
 *
 * The footer now states the one thing this component can actually know from
 * auth state â€” the deployment's access mode â€” and links to the network
 * explorer for anything about chain health. Real chain status is fetched live
 * on that page and is shown as unavailable when it is unavailable.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  BarChart3,
  CircleHelp,
  FileChartColumn,
  FileSearch,
  GitBranch,
  LayoutDashboard,
  Search,
  ShieldCheck,
} from "lucide-react";

import { NavDocuments } from "@/components/nav-documents";
import { NavMain } from "@/components/nav-main";
import { NavSecondary } from "@/components/nav-secondary";
import { NavUser } from "@/components/nav-user";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";
import { CHAIN_ORDER, chainShort } from "@/lib/format";

/**
 * Navigation grouped by what an investigator is doing, not by what the app is
 * built from.
 *
 * The previous grouping was "Investigation" (dashboard, trace, investigations,
 * risk) then "Intelligence" (reports, entities), which split the workflow in
 * half: opening a case and exporting it lived in different sections, and
 * "Network Explorer" sat apart in the footer next to Help as though chain
 * health were a support topic rather than an investigation one.
 *
 * The order now follows the job. Start a trace, then find the cases and outputs
 * that come out of it, then the aggregate views across cases.
 *
 * Every entry is a route that already existed. Nothing was added or removed.
 */
const data = {
  investigate: [
    { title: "Dashboard", to: "/app", icon: <LayoutDashboard /> },
    { title: "Trace a Wallet", to: "/app/trace", icon: <Search /> },
  ],
  cases: [
    { name: "Investigations", to: "/app/investigations", icon: <FileSearch /> },
    { name: "Investigation Reports", to: "/app/reports", icon: <FileChartColumn /> },
    { name: "Entity Intelligence", to: "/app/entities", icon: <ShieldCheck /> },
  ],
  analytics: [
    { title: "Risk Analytics", to: "/app/risk", icon: <BarChart3 /> },
    { title: "Network Explorer", to: "/app/network", icon: <GitBranch /> },
  ],
  navSecondary: [
    { title: "Help & Method", to: "/app/help", icon: <CircleHelp /> },
  ],
};

/**
 * The chains this deployment actually serves, read from `/network/chains`.
 *
 * Fetched rather than hard-coded, because the adapter registry is the
 * authority on which chains exist. If the backend is unreachable the count
 * says so rather than showing five grey dots that look like five working
 * networks.
 */
function ChainStrip() {
  const [chains, setChains] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .chains()
      .then((list) => {
        if (live && Array.isArray(list)) setChains(list);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, []);

  if (failed || !chains) {
    return (
      <p className="text-[10px] text-muted-foreground">
        {failed ? "Chain list unavailable" : "Reading chain list…"}
      </p>
    );
  }

  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {CHAIN_ORDER.filter((c) => chains.some((entry) => entry.chain === c)).map((c) => {
        const entry = chains.find((e) => e.chain === c);
        return (
          <span
            key={c}
            title={entry?.limitation || `${entry?.chain_name || c}: no declared limitation`}
            className="rounded border border-border bg-background px-1.5 py-0.5 text-[9px] font-semibold tracking-wider text-foreground"
          >
            {chainShort(c)}
          </span>
        );
      })}
    </div>
  );
}

export function AppSidebar({ ...props }) {
  const { isDemo, isAuthenticated, status } = useAuth();

  const modeLabel = isDemo
    ? "DEMO MODE"
    : isAuthenticated
      ? "SIGNED IN"
      : status?.mode === "locked"
        ? "LOCKED"
        : "READING…";

  const modeDetail = isDemo
    ? "Open access — not private"
    : isAuthenticated
      ? "Cases are scoped to your account"
      : status?.mode === "locked"
        ? "Sign-in required"
        : "Checking deployment access";

  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            {/*
              The brand mark, at the size the sidebar actually renders it.

              Two files rather than one styled with a filter: the mark's navy ink
              is genuinely invisible on the dark shell, and a CSS filter that
              made it visible would also wash out the two blues that carry the
              brand. So the dark-surface file is the artwork with its navy lifted
              to white, generated by tools/build_brand_assets.py, and the two are
              swapped with the theme.

              The wordmark stays live text rather than becoming part of the image.
              An image of "BlockTrace" cannot be read by a screen reader, and
              type stays sharp at every size the sidebar collapses to.
            */}
            <SidebarMenuButton
              className="data-[slot=sidebar-menu-button]:h-11 data-[slot=sidebar-menu-button]:p-1.5!"
              render={<Link to="/app" />}
            >
              <img
                src="/brand/blocktrace-mark.png"
                alt=""
                width={28}
                height={28}
                className="size-7 shrink-0 dark:hidden"
              />
              <img
                src="/brand/blocktrace-mark-on-dark.png"
                alt=""
                width={28}
                height={28}
                className="hidden size-7 shrink-0 dark:block"
              />
              <span className="text-base font-semibold tracking-tight">
                BlockTrace
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <NavMain items={data.investigate} label="Investigate" />

        <NavDocuments items={data.cases} label="Cases" />

        <NavMain items={data.analytics} label="Analytics" />

        <NavSecondary items={data.navSecondary} className="mt-auto" />
      </SidebarContent>

      <SidebarFooter>
        <div className="mx-2 mb-2 rounded-lg border border-border bg-muted/50 p-3">
          <div className="flex items-center gap-2">
            {/* A dot here would imply a heartbeat. The label states a fact about
                the deployment, and the chain list below is fetched live. */}
            <span className="text-[10px] font-semibold tracking-[0.16em] text-foreground">
              {modeLabel}
            </span>
          </div>
          <p className="mt-1 text-[10px] text-muted-foreground">{modeDetail}</p>
          <ChainStrip />
        </div>

        <NavUser />
      </SidebarFooter>
    </Sidebar>
  );
}


