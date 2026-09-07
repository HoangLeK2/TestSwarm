import { buildDashboardNavItems } from '@/config/dashboard-nav';
import {
  filterNavItemsByAccess,
  normalizeNavOrgRole,
  normalizeNavUserRole
} from '@/lib/nav-access';
import type { NavItem } from '@/types';
import { useTranslations } from 'next-intl';
import { useUser } from '@/features/auth';
import { useCan } from '@/features/auth/hooks/use-permission';

export function useNavItems(options?: { adminCenter?: boolean }): {
  baseItems: NavItem[];
  settingItems: NavItem[];
} {
  const t = useTranslations('navigation');
  const { user } = useUser();
  const { can, ready } = useCan();
  const role = normalizeNavUserRole(user?.role);
  const orgRole = normalizeNavOrgRole(user?.orgRole);

  const { baseItems, settingItems, adminItems } = buildDashboardNavItems(
    (key) => t(key as Parameters<typeof t>[0])
  );

  if (!ready) {
    return { baseItems: [], settingItems: [] };
  }

  const ctx = { userRole: role, orgRole, can };
  const visibleBaseItems = options?.adminCenter ? adminItems : baseItems;

  return {
    baseItems: filterNavItemsByAccess(visibleBaseItems, ctx),
    settingItems: filterNavItemsByAccess(settingItems, ctx)
  };
}
