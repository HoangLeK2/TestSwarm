import { ROUTES } from '@/config/routes';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { NavItem } from '@/types';
import { useTranslations } from 'next-intl';

export function useNavItems(): {
  baseItems: NavItem[];
  settingItems: NavItem[];
} {
  const t = useTranslations('navigation');
  const { currentOrg } = useOrganization();
  const baseItems: NavItem[] = [
    {
      title: t('devices'),
      type: 'group',
      items: [
        {
          title: t('device_farm'),
          url: ROUTES.DEVICES.ROOT,
          icon: 'laptop'
        },
        {
          title: t('devices_manage'),
          url: ROUTES.DEVICES.MANAGE,
          icon: 'smartphone'
        },
        {
          title: t('device_control_record'),
          url: ROUTES.DEVICES.CONTROL_RECORD,
          icon: 'laptop'
        },
        {
          title: t('campaigns'),
          url: ROUTES.CAMPAIGNS.ROOT,
          icon: 'play'
        },
        {
          title: t('schedules'),
          url: ROUTES.SCHEDULES.ROOT,
          icon: 'bell'
        },
        {
          title: t('device_groups'),
          url: ROUTES.DEVICE_GROUPS.ROOT,
          icon: 'folder'
        },
        {
          title: t('accounts'),
          url: ROUTES.ACCOUNTS.ROOT,
          icon: 'user'
        },
        {
          title: t('scenario_templates'),
          url: ROUTES.SCENARIO_TEMPLATES.ROOT,
          icon: 'template'
        },
        {
          title: t('content'),
          url: ROUTES.CONTENT.ROOT,
          icon: 'stats'
        }
      ]
    }
  ];

  const settingItems: NavItem[] = [
    {
      title: t('organization'),
      type: 'group',
      items: [
        {
          title: t('organization_general'),
          url: ROUTES.DASHBOARD.ORGANIZATION_SETTINGS(currentOrg?.id || ''),
          icon: 'settings'
        },
        {
          title: t('members'),
          url: ROUTES.DASHBOARD.ORGANIZATION_MEMBER(currentOrg?.id || ''),
          icon: 'user'
        }
      ]
    },
    {
      title: t('developer'),
      type: 'group',
      items: [
        {
          title: t('api_keys'),
          url: ROUTES.DASHBOARD.API_KEYS(currentOrg?.id || ''),
          icon: 'key'
        }
      ]
    },
    {
      title: t('totp'),
      type: 'group',
      items: [
        {
          title: t('totp'),
          url: ROUTES.DASHBOARD.TOTP(currentOrg?.id || ''),
          icon: 'settings'
        }
      ]
    }
  ];

  return {
    baseItems,
    settingItems
  };
}
