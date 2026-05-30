import { Icons } from '@/components/icons';
import type { NavUserRole, PermissionRequirement } from '@/lib/nav-access';

export interface NavItem {
  title: string;
  url?: string;
  disabled?: boolean;
  external?: boolean;
  shortcut?: [string, string];
  icon?: keyof typeof Icons;
  label?: string;
  description?: string;
  isActive?: boolean;
  items?: NavItem[];
  type?: 'group' | 'item' | 'divider';
  /** When set, item is visible only to these platform roles (see /auth/me role). */
  roles?: readonly NavUserRole[];
  /** RBAC gate — hidden when caller lacks this permission (see lib/rbac). */
  permission?: PermissionRequirement;
}

export interface NavItemWithChildren extends NavItem {
  items: NavItemWithChildren[];
}

export interface NavItemWithOptionalChildren extends NavItem {
  items?: NavItemWithChildren[];
}

export interface FooterItem {
  title: string;
  items: {
    title: string;
    href: string;
    external?: boolean;
  }[];
}

export type MainNavItem = NavItemWithOptionalChildren;

export type SidebarNavItem = NavItemWithChildren;
