/**
 * Primary navigation.
 *
 * Every entry is a real route. The previous version pointed every item at `#`,
 * which meant a sidebar that looked navigable and went nowhere — the single
 * most common way a prototype betrays that it is a prototype.
 *
 * Active state is prefix matching rather than exact equality, so a deep link
 * like `/app/investigations/<id>` still lights up "Investigations" instead of
 * leaving every item grey. `/app` itself is exact, or it would light up on
 * every route and the operator could never tell which section they are in.
 */

import { NavLink, useLocation } from "react-router-dom";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

/**
 * Is this the active route?
 *
 * Trailing slashes are normalised so `/app/network/` and `/app/network` agree.
 */
export function isRouteActive(pathname, to) {
  const current = String(pathname || "").replace(/\/+$/, "") || "/";
  const target = String(to || "").replace(/\/+$/, "") || "/";
  if (target === "/app") return current === "/app";
  return current === target || current.startsWith(`${target}/`);
}

export function NavMain({ items }) {
  const { pathname } = useLocation();

  return (
    <SidebarGroup>
      <SidebarGroupContent className="flex flex-col gap-2">
        <SidebarMenu>
          {items.map((item) => (
            <SidebarMenuItem key={item.to ?? item.title}>
              <SidebarMenuButton
                tooltip={item.title}
                isActive={isRouteActive(pathname, item.to)}
                render={<NavLink to={item.to} end={item.to === "/app"} />}
              >
                {item.icon}
                <span>{item.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
