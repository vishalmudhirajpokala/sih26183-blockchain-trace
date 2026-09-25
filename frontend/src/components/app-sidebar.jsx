/**
 * The application sidebar.
 *
 * Two things were wrong with the scaffold and both are RULE 5 violations:
 *
 * 1. Every nav item pointed at `#`.
 * 2. The footer read "TRON NETWORK / Mainnet · Live data" with a green dot,
 *    hard-coded. It was not a measurement of anything. It was a decoration
 *    asserting that a live multi-chain tool was connected to one specific
 *    network, which is both false (it is multi-chain) and unfalsifiable (it
 *    could never notice the API going down).
 *
 * The footer now states the one thing this component can actually know from
 * auth state — the deployment's access mode — and links to the network
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

const data = {
  navMain: [
    { title: "Dashboard", to: "/app", icon: <LayoutDashboard /> },
    { title: "Trace Console", to: "/app/trace", icon: <Search /> },
    { title: "Investigations", to: "/app/investigations", icon: <FileSearch /> },
    { title: "Risk Analytics", to: "/app/risk", icon: <BarChart3 /> },
  ],
  navSecondary: [
    { title: "Network Explorer", to: "/app/network", icon: <GitBranch /> },
    { title: "Help & Method", to: "/app/help", icon: <CircleHelp /> },
  ],
  documents: [
    { name: "Investigation Reports", to: "/app/reports", icon: <FileChartColumn /> },
    { name: "Entity Intelligence", to: "/app/entities", icon: <ShieldCheck /> },
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
      <p className="text-[10px] text-slate-500">
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
            className="rounded bg-slate-800/80 px-1.5 py-0.5 text-[9px] font-semibold tracking-wider text-slate-300"
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
            <SidebarMenuButton
              className="h-11 p-1.5! hover:bg-slate-800/70"
              render={<Link to="/app" />}
            >
              <span className="flex size-7 items-center justify-center rounded-md bg-blue-500 text-xs font-bold text-white">
                BT
              </span>
              <span className="text-base font-bold tracking-tight text-white">
                BlockTrace
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <div className="px-3 pb-2 pt-3 text-[10px] font-semibold tracking-[0.16em] text-slate-500">
          INVESTIGATION
        </div>

        <NavMain items={data.navMain} />

        <div className="px-3 pb-2 pt-5 text-[10px] font-semibold tracking-[0.16em] text-slate-500">
          INTELLIGENCE
        </div>

        <NavDocuments items={data.documents} />

        <NavSecondary items={data.navSecondary} className="mt-auto" />
      </SidebarContent>

      <SidebarFooter>
        <div className="mx-2 mb-2 rounded-lg border border-slate-800 bg-slate-900/70 p-3">
          <div className="flex items-center gap-2">
            {/* A dot here would imply a heartbeat. The label states a fact about
                the deployment, and the chain list below is fetched live. */}
            <span className="text-[10px] font-semibold tracking-[0.16em] text-slate-400">
              {modeLabel}
            </span>
          </div>
          <p className="mt-1 text-[10px] text-slate-500">{modeDetail}</p>
          <ChainStrip />
        </div>

        <NavUser />
      </SidebarFooter>
    </Sidebar>
  );
}
