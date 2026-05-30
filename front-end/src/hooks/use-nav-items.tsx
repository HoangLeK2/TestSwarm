import { buildDashboardNavItems } from '@/config/dashboard-nav';
import {
  filterNavItemsByAccess,
  normalizeNavUserRole
} from '@/lib/nav-access';
import type { NavItem } from '@/types';
import { useTranslations } from 'next-intl';
import { useUser } from '@/features/auth';
import { useCan } from '@/features/auth/hooks/use-permission';

export function useNavItems(): {
  baseItems: NavItem[];
  settingItems: NavItem[];
} {
  const t = useTranslations('navigation');
  const { user } = useUser();
  const { can, ready } = useCan();
  const role = normalizeNavUserRole(user?.role);

  const { baseItems, settingItems } = buildDashboardNavItems((key) =>
    t(key as Parameters<typeof t>[0])
  );

  if (!ready) {
    return { baseItems: [], settingItems: [] };
  }

  const ctx = { userRole: role, can };

  return {
    baseItems: filterNavItemsByAccess(baseItems, ctx),
    settingItems: filterNavItemsByAccess(settingItems, ctx)
  };
}
