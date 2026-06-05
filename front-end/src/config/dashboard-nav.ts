import { ROUTES } from '@/config/routes';
import type { Icons } from '@/components/icons';
import type { NavItem } from '@/types';
import type { NavUserRole, PermissionRequirement } from '@/lib/nav-access';

type NavIcon = keyof typeof Icons;

type NavLeafDef = {
  titleKey: string;
  url: string;
  icon: NavIcon;
  roles?: NavUserRole[];
  permission?: PermissionRequirement;
};

type NavGroupDef = {
  titleKey: string;
  items: NavLeafDef[];
};

const DAILY_OPERATIONS_GROUP: NavGroupDef = {
  titleKey: 'nav_group_daily_operations',
  items: [
    {
      titleKey: 'device_farm',
      url: ROUTES.DEVICES.ROOT,
      icon: 'laptop',
      permission: { object: 'devices', action: 'read' }
    },
    {
      titleKey: 'device_control_record',
      url: ROUTES.DEVICES.CONTROL_RECORD,
      icon: 'laptop',
      permission: { object: 'devices', action: 'execute' }
    },
    {
      titleKey: 'campaigns',
      url: ROUTES.CAMPAIGNS.ROOT,
      icon: 'play',
      permission: { object: 'campaigns', action: 'read' }
    },
    {
      titleKey: 'content',
      url: ROUTES.CONTENT.ROOT,
      icon: 'stats',
      permission: { object: 'content', action: 'read' }
    }
  ]
};

const PREPARATION_GROUP: NavGroupDef = {
  titleKey: 'nav_group_preparation',
  items: [
    {
      titleKey: 'org_scenarios',
      url: ROUTES.ORG_SCENARIOS.ROOT,
      icon: 'flow',
      permission: { object: 'scenarios', action: 'read' }
    },
    {
      titleKey: 'accounts',
      url: ROUTES.ACCOUNTS.ROOT,
      icon: 'user',
      permission: { object: 'accounts', action: 'read' }
    },
    {
      titleKey: 'account_groups',
      url: ROUTES.ACCOUNT_GROUPS.ROOT,
      icon: 'usersGroup',
      permission: { object: 'account-groups', action: 'read' }
    },
    {
      titleKey: 'device_groups',
      url: ROUTES.DEVICE_GROUPS.ROOT,
      icon: 'folder',
      permission: { object: 'device-groups', action: 'read' }
    }
  ]
};

const ADMIN_MONITORING_GROUP: NavGroupDef = {
  titleKey: 'nav_group_admin_monitoring',
  items: [
    {
      titleKey: 'devices_manage',
      url: ROUTES.DEVICES.MANAGE,
      icon: 'smartphone',
      permission: { object: 'devices', action: 'read' }
    },
    {
      titleKey: 'schedules',
      url: ROUTES.SCHEDULES.ROOT,
      icon: 'calendarTime',
      permission: { object: 'schedules', action: 'read' }
    },
    {
      titleKey: 'notifications',
      url: ROUTES.NOTIFICATIONS.ROOT,
      icon: 'bell',
      permission: { object: 'notifications', action: 'read' }
    },
    {
      // Temporary: analytics rollout — superadmin platform accounts only.
      titleKey: 'analytics',
      url: ROUTES.ANALYTICS.ROOT,
      icon: 'stats',
      roles: ['superadmin']
    },
    {
      titleKey: 'activity_history',
      url: ROUTES.DASHBOARD.ACTIVITY_HISTORY.ROOT,
      icon: 'history',
      permission: { object: 'analytics', action: 'read' }
    }
  ]
};

const ORGANIZATION_GROUP: NavGroupDef = {
  titleKey: 'organization',
  items: [
    {
      titleKey: 'organizations_list',
      url: ROUTES.DASHBOARD.ORGANIZATION_LIST,
      icon: 'building',
      roles: ['superadmin']
    },
    {
      titleKey: 'organization_general',
      url: ROUTES.DASHBOARD.ORGANIZATION,
      icon: 'settings',
      permission: { object: 'organizations', action: 'read' }
    },
    {
      titleKey: 'members',
      url: ROUTES.DASHBOARD.ORGANIZATION_MEMBER,
      icon: 'user',
      permission: { object: 'organizations', action: 'read' }
    }
  ]
};

const INFRASTRUCTURE_GROUP: NavGroupDef = {
  titleKey: 'infrastructure',
  items: [
    {
      titleKey: 'relay_agents',
      url: ROUTES.RELAY_AGENTS.ROOT,
      icon: 'server',
      permission: { object: 'relay-agents', action: 'read' }
    },
    {
      titleKey: 'mcp_tokens',
      url: ROUTES.MCP.ROOT,
      icon: 'key',
      permission: { object: 'mcp', action: 'read' }
    }
  ]
};

export const DASHBOARD_MAIN_NAV_GROUPS = [
  DAILY_OPERATIONS_GROUP,
  PREPARATION_GROUP,
  ADMIN_MONITORING_GROUP
] as const;

export const DASHBOARD_SETTINGS_NAV_GROUPS = [
  ORGANIZATION_GROUP,
  INFRASTRUCTURE_GROUP
] as const;

export const DASHBOARD_NAV_PATHS: string[] = [
  ...DASHBOARD_MAIN_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.url)),
  ...DASHBOARD_SETTINGS_NAV_GROUPS.flatMap((g) => g.items.map((i) => i.url))
];

function leafFromDef(def: NavLeafDef, t: (key: string) => string): NavItem {
  return {
    title: t(def.titleKey),
    url: def.url,
    icon: def.icon,
    roles: def.roles,
    permission: def.permission
  };
}

function groupFromDef(def: NavGroupDef, t: (key: string) => string): NavItem {
  return {
    title: t(def.titleKey),
    type: 'group',
    items: def.items.map((leaf) => leafFromDef(leaf, t))
  };
}

export function buildDashboardNavItems(t: (key: string) => string): {
  baseItems: NavItem[];
  settingItems: NavItem[];
} {
  return {
    baseItems: DASHBOARD_MAIN_NAV_GROUPS.map((g) => groupFromDef(g, t)),
    settingItems: DASHBOARD_SETTINGS_NAV_GROUPS.map((g) => groupFromDef(g, t))
  };
}
