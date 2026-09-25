/**
 * Secondary navigation. Same real-route rule as `NavMain`.
 */

import { NavLink, useLocation } from "react-router-dom";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

import { isRouteActive } from "@/components/nav-main";

export function NavSecondary({ items, ...props }) {
  const { pathname } = useLocation();

  return (
    <SidebarGroup {...props}>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => (
            <SidebarMenuItem key={item.to ?? item.title}>
              <SidebarMenuButton
                tooltip={item.title}
                isActive={isRouteActive(pathname, item.to)}
                render={<NavLink to={item.to} />}
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
