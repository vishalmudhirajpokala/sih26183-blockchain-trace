/**
 * Intelligence navigation: reports, entities, network explorer.
 *
 * The scaffold version put a "⋯" dropdown on each row with Open / Share /
 * Delete. None of those did anything, and "Delete" in particular is the worst
 * possible dead control to ship next to real investigations — an operator who
 * clicks it is told nothing, and reasonably concludes the row is gone when it
 * is not. The rows are now plain routes, and the destructive action lives
 * where it belongs, on the investigation itself, behind a confirmation.
 */

import { NavLink, useLocation } from "react-router-dom";

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

import { isRouteActive } from "@/components/nav-main";

export function NavDocuments({ items, label = "Intelligence" }) {
  const { pathname } = useLocation();

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{label}</SidebarGroupLabel>
      <SidebarMenu>
        {items.map((item) => (
          <SidebarMenuItem key={item.to ?? item.name}>
            <SidebarMenuButton
              tooltip={item.name}
              isActive={isRouteActive(pathname, item.to)}
              render={<NavLink to={item.to} />}
            >
              {item.icon}
              <span>{item.name}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  );
}
