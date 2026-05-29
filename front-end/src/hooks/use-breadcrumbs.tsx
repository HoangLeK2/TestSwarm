'use client';

import { usePathname } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';
import { useMemo } from 'react';

//mapping for breadcrumbs
const routeMapping: Record<string, string[]> = {
  '/dashboard': [],
  '/dashboard/campaigns': ['navigation.dashboard', 'navigation.campaigns'],
  '/dashboard/devices': ['navigation.dashboard', 'navigation.devices'],
  '/dashboard/schedules': ['navigation.dashboard', 'navigation.schedules'],
  '/dashboard/activity-history': [
    'navigation.dashboard',
    'navigation.activity_history'
  ],
  '/dashboard/scenario-templates': [
    'navigation.dashboard',
    'navigation.scenario_templates'
  ],
  '/dashboard/device-groups': [
    'navigation.dashboard',
    'navigation.device_groups'
  ],
  '/dashboard/accounts': ['navigation.dashboard', 'navigation.accounts'],
  '/dashboard/device-farm/account-groups': [
    'navigation.dashboard',
    'navigation.account_groups'
  ],
  '/dashboard/content': ['navigation.dashboard', 'navigation.content'],
  '/dashboard/relay-agents': [
    'navigation.dashboard',
    'navigation.relay_agents'
  ],
  '/dashboard/product': ['navigation.dashboard', 'navigation.products'],
  '/dashboard/profile': ['navigation.dashboard', 'navigation.profile'],
  '/dashboard/statistic': ['navigation.dashboard', 'navigation.statistic'],
  '/dashboard/admin/organization': [
    'navigation.dashboard',
    'navigation.organization'
  ],
  '/dashboard/faq': ['navigation.faq'],
  '/dashboard/flow': ['navigation.dashboard', 'navigation.flow-vc'],
  '/dashboard/settings': ['navigation.settings'],
  '/dashboard/inventory': ['navigation.dashboard', 'navigation.inventory'],
  '/dashboard/product/sync': ['navigation.sync'],
  '/dashboard/settings/organization/members': [
    'navigation.settings',
    'navigation.members'
  ],
  '/dashboard/settings/organization': [
    'navigation.settings',
    'navigation.organization_general'
  ],
  '/dashboard/gln': ['navigation.dashboard', 'navigation.gln']
};

export function useBreadcrumbs() {
  const pathname = usePathname();
  const t = useTranslations();

  const breadcrumbs = useMemo(() => {
    const segments = pathname.split('/').filter(Boolean);

    // Check for exact match first
    if (routeMapping[pathname]) {
      return routeMapping[pathname].map((translationKey, index) => {
        const path = `/${segments.slice(0, index + 1).join('/')}`;
        return {
          title: t(translationKey),
          link: path
        };
      });
    }

    const dynamicMatch = Object.keys(routeMapping).find((routeKey) => {
      const routeSegments = routeKey.split('/').filter(Boolean);
      if (routeSegments.length !== segments.length) return false;

      return routeSegments.every((seg, idx) => {
        if (seg.startsWith(':')) return true;
        return seg === segments[idx];
      });
    });

    if (dynamicMatch) {
      const routeSegments = dynamicMatch.split('/').filter(Boolean);
      return routeMapping[dynamicMatch].map((translationKey, index) => {
        const pathSegments = [];
        for (let i = 0; i <= index; i++) {
          if (routeSegments[i] && routeSegments[i].startsWith(':')) {
            pathSegments.push(segments[i]);
          } else if (routeSegments[i]) {
            pathSegments.push(routeSegments[i]);
          } else if (segments[i]) {
            pathSegments.push(segments[i]);
          }
        }
        return {
          title: t(translationKey),
          link: '/' + pathSegments.join('/')
        };
      });
    }

    return segments.map((segment, index) => {
      const path = `/${segments.slice(0, index + 1).join('/')}`;
      let title = segment.charAt(0).toUpperCase() + segment.slice(1);
      try {
        if (segment === 'dashboard') title = t('navigation.dashboard');
        else if (segment === 'campaigns') title = t('navigation.campaigns');
        else if (segment === 'devices') title = t('navigation.devices');
        else if (segment === 'schedules') title = t('navigation.schedules');
        else if (segment === 'device-groups')
          title = t('navigation.device_groups');
        else if (segment === 'accounts') title = t('navigation.accounts');
        else if (segment === 'account-groups')
          title = t('navigation.account_groups');
        else if (segment === 'scenario-templates')
          title = t('navigation.scenario_templates');
        else if (segment === 'device-farm') title = t('navigation.device_farm');
        else if (segment === 'content') title = t('navigation.content');
        else if (segment === 'relay-agents')
          title = t('navigation.relay_agents');
        else if (segment === 'product') title = t('navigation.products');
        else if (segment === 'profile') title = t('navigation.profile');
        else if (segment === 'edit') title = t('common.edit');
        else if (segment === 'create') title = t('common.create');
        else if (segment === 'organization')
          title = t('navigation.organization');
        else if (segment === 'batches') title = t('navigation.batches');
        else if (segment === 'sgtin') title = t('navigation.sgtin');
        else if (segment === 'faq') title = t('navigation.faq');
        else if (segment === 'flow') title = t('navigation.flow');
        else if (segment === 'settings') title = t('navigation.settings');
        else if (segment === 'member') title = t('navigation.members');
        else if (segment === 'activity-history')
          title = t('navigation.activity_history');
        else if (segment === 'gln') title = t('navigation.gln');
      } catch {}
      return {
        title,
        link: path
      };
    });
  }, [pathname, t]);

  const filteredBreadcrumbs = breadcrumbs?.filter((breadcrumb, index, arr) => {
    if (
      index === 0 &&
      breadcrumb.link.includes('/dashboard') &&
      arr[1]?.link?.includes('/settings')
    ) {
      return false;
    }
    return true;
  });

  return filteredBreadcrumbs;
}
