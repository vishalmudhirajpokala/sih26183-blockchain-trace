/**
 * The account menu.
 *
 * It shows the identity the *server* has, not a hard-coded one. The scaffold
 * rendered "Investigator / BlockTrace Console" with a photo that does not
 * exist, which is the same class of error as a fake block height: a detail
 * that looks like it came from somewhere and did not.
 *
 * The Account / Billing / Notifications entries are gone rather than disabled.
 * They have no endpoints behind them, and a disabled control that never
 * becomes enabled is a promise this codebase should not make.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CircleUserRoundIcon, LogOutIcon, TriangleAlertIcon } from "lucide-react";

import {
  Avatar,
  AvatarFallback,
} from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { EllipsisVerticalIcon } from "lucide-react";

import { useAuth } from "@/hooks/use-auth";

/** Two initials from whatever name we have, or nothing. */
function initials(name, email) {
  const source = String(name || email || "");
  const parts = source.split(/[\s.@_-]+/).filter(Boolean);
  if (parts.length === 0) return "BT";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

export function NavUser() {
  const { isMobile } = useSidebar();
  const { user, isDemo, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  const name = user?.name || "Signed out";
  const email = user?.email || "No session";

  async function handleLogout() {
    setBusy(true);
    try {
      await logout();
      // Navigate explicitly rather than relying on the guard: the guard will
      // send them to /login, but only after a re-render, and an operator who
      // clicks "Log out" and stays on a case page has every reason to think it
      // failed.
      navigate("/login", { replace: true });
      toast.success("Signed out. Local session data was cleared.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton size="lg" className="aria-expanded:bg-muted" />
            }
          >
            <Avatar className="size-8 rounded-lg">
              <AvatarFallback className="rounded-lg">{initials(user?.name, user?.email)}</AvatarFallback>
            </Avatar>
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-medium">{name}</span>
              <span className="truncate text-xs text-foreground/70">{email}</span>
            </div>
            <EllipsisVerticalIcon className="ml-auto size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-56"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuGroup>
              <DropdownMenuLabel className="p-0 font-normal">
                <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                  <Avatar className="size-8">
                    <AvatarFallback className="rounded-lg">{initials(user?.name, user?.email)}</AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 text-left text-sm leading-tight">
                    <span className="truncate font-medium">{name}</span>
                    <span className="truncate text-xs text-muted-foreground">{email}</span>
                  </div>
                </div>
              </DropdownMenuLabel>
            </DropdownMenuGroup>

            <DropdownMenuSeparator />

            {isDemo ? (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
                <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  Demo mode. No account is signed in and nothing here is private
                  to you.
                </span>
              </div>
            ) : null}

            {isAuthenticated ? (
              <DropdownMenuItem onClick={() => navigate("/app")}>
                <CircleUserRoundIcon />
                Go to dashboard
              </DropdownMenuItem>
            ) : null}

            <DropdownMenuSeparator />

            <DropdownMenuItem
              onClick={handleLogout}
              disabled={busy}
            >
              <LogOutIcon />
              {isAuthenticated ? "Log out" : "Leave demo mode"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
