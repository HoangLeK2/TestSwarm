export const ROUTES = {
  AUTH: {
    SIGN_IN: '/auth/sign-in',
    SIGN_UP: '/auth/sign-up',
    ACCEPT_INVITE: '/auth/accept-invite',
    FORGOT_PASSWORD: '/auth/forgot-password',
    RESET_PASSWORD: '/auth/reset-password',
    VERIFY_EMAIL: '/auth/verify-email',
    TOTP: '/auth/totp'
  },
  PRODUCT: {
    ROOT: '/dashboard/product',
    CREATE: '/dashboard/product/create',
    SYNC: '/dashboard/product/sync',
    EDIT: (id: string) => `/dashboard/product/${id}/edit`,
    VIEW: (id: string) => `/dashboard/product/${id}`
  },
  DEVICES: {
    ROOT: '/dashboard/device-farm',
    MANAGE: '/dashboard/devices',
    DETAIL: (serial: string) =>
      `/dashboard/devices/${encodeURIComponent(serial)}`,
    CONTROL_RECORD: '/dashboard/device-farm/control',
    /** Điều khiển thiết bị với serial đã chọn (để vào đúng màn hình rồi lấy XML). */
    CONTROL_RECORD_WITH_SERIAL: (serial: string) =>
      `/dashboard/device-farm/control?serial=${encodeURIComponent(serial)}`,
    /** Mở trang điều khiển để chỉnh sửa một scenario cụ thể của campaign. */
    CONTROL_RECORD_EDIT_SCENARIO: (
      campaignId: string,
      scenarioId: string,
      serial?: string
    ) => {
      const params = new URLSearchParams({ campaignId, scenarioId });
      if (serial) params.set('serial', serial);
      return `/dashboard/device-farm/control?${params.toString()}`;
    }
    ,
    /** Mở trang điều khiển để ghi và lưu vào kịch bản tổ chức. */
    CONTROL_RECORD_EDIT_ORG_SCENARIO: (
      orgScenarioId: string,
      opts?: { serial?: string; returnTo?: string }
    ) => {
      const params = new URLSearchParams({ orgScenarioId });
      if (opts?.serial) params.set('serial', opts.serial);
      if (opts?.returnTo) params.set('returnTo', opts.returnTo);
      return `/dashboard/device-farm/control?${params.toString()}`;
    }
  },
  CAMPAIGNS: {
    ROOT: '/dashboard/campaigns',
    /** Campaign list with row scroll/highlight (monitor opens manually). */
    DETAIL: (id: string) =>
      `/dashboard/campaigns?campaign_id=${encodeURIComponent(id)}`,
    MONITOR: (id: string) =>
      `/dashboard/campaigns/${encodeURIComponent(id)}/monitor`
  },
  DEVICE_GROUPS: {
    ROOT: '/dashboard/device-groups'
  },
  ACCOUNTS: {
    ROOT: '/dashboard/accounts'
  },
  ACCOUNT_GROUPS: {
    ROOT: '/dashboard/device-farm/account-groups'
  },
  SCENARIO_TEMPLATES: {
    ROOT: '/dashboard/scenario-templates',
    FLOW: (id: string) => `/scenario-flow/${id}`
  },
  ORG_SCENARIOS: {
    ROOT: '/dashboard/org-scenarios',
    /** Opens org scenario library with detail sheet for this scenario. */
    DETAIL: (scenarioId: string) =>
      `/dashboard/org-scenarios?scenario_id=${encodeURIComponent(scenarioId)}`,
    /** Flowgram editor for graph-kind org scenarios. */
    FLOW_EDIT: (scenarioId: string, opts?: { returnTo?: string }) => {
      const base = `/scenario-flow/org/${encodeURIComponent(scenarioId)}`;
      if (!opts?.returnTo?.trim()) return base;
      const params = new URLSearchParams({
        returnTo: opts.returnTo.trim()
      });
      return `${base}?${params.toString()}`;
    }
  },
  SCHEDULES: {
    ROOT: '/dashboard/schedules'
  },
  RELAY_AGENTS: {
    ROOT: '/dashboard/relay-agents'
  },
  CONTENT: {
    ROOT: '/dashboard/content',
    DETAIL: (id: string) => `/dashboard/content/${id}`,
    EXPORTS: '/dashboard/content/exports',
    /** Jump to content page pre-filtered by campaign */
    BY_CAMPAIGN: (campaignId: string) =>
      `/dashboard/content?campaign_id=${encodeURIComponent(campaignId)}`,
    BY_EXECUTION: (executionId: string) =>
      `/dashboard/content?execution_id=${encodeURIComponent(executionId)}`
  },
  NOTIFICATIONS: {
    ROOT: '/dashboard/notifications',
    INBOX: '/dashboard/notifications?tab=inbox',
    CHANNELS: '/dashboard/notifications?tab=channels'
  },
  ANALYTICS: {
    ROOT: '/dashboard/analytics',
    ACTIVITY: '/dashboard/analytics?tab=activity',
    AUDIT: '/dashboard/analytics?tab=audit'
  },
  MCP: {
    ROOT: '/dashboard/mcp',
    TOKENS: '/dashboard/mcp/tokens',
    AUDIT: '/dashboard/mcp/audit-log',
    TOOLS: '/dashboard/mcp/tools',
    SANDBOX: '/dashboard/mcp/sandbox'
  },
  DASHBOARD: {
    ROOT: '/dashboard',
    PROFILE: '/dashboard/settings/profile',
    ORGANIZATION: '/dashboard/settings/organization',
    ORGANIZATION_LIST: '/dashboard/settings/organizations',
    ORGANIZATION_MEMBER: '/dashboard/settings/organization/members',
    /** @deprecated Use ORGANIZATION; org is resolved from context, not URL. */
    ORGANIZATION_SETTINGS: (_id?: string) => '/dashboard/settings/organization',
    ORGANIZATION_EDIT: (id: string) => `/dashboard/settings/organization/${id}`,
    PRODUCT: {
      ROOT: '/dashboard/product',
      CREATE: '/dashboard/product/create',
      SYNC: '/dashboard/product/sync',
      EDIT: (id: string) => `/dashboard/product/${id}/edit`
    },
    BATCH: {
      ROOT: '/dashboard/batches',
      CREATE: '/dashboard/batches/create',
      EDIT: (id: string) => `/dashboard/batches/${id}/edit`,
      DETAIL: (id: string) => `/dashboard/batches/${id}`
    },
    STATISTIC: '/dashboard/statistic',
    FAQ: '/dashboard/faq',
    VC_RELEASE: {
      ROOT: '/dashboard/vc-release',
      FLOW: '/dashboard/vc-release/flow',
      PRODUCT_DETAIL: (productId: string, productName: string, gtin: string) =>
        `/dashboard/vc-release/${productId}?productName=${productName}&gtin=${gtin}`,
      BATCH_DETAIL: (batchName: string) =>
        `/dashboard/vc-release/batch/${batchName}`,
      SGTIN_DETAIL: (sgtin: string) => `/dashboard/vc-release/sgtin/${sgtin}`
    },
    VC_REVOKE: {
      ROOT: '/dashboard/vc-revoke',
      FLOW: '/dashboard/vc-revoke/flow',
      SGTIN_DETAIL: (sgtin: string) => `/dashboard/vc-revoke/sgtin/${sgtin}`,
      BATCH_DETAIL: (batchId: string) => `/dashboard/vc-revoke/batch/${batchId}`
    },
    GLN: {
      ROOT: '/dashboard/gln'
    },
    ACTIVITY_HISTORY: {
      ROOT: '/dashboard/activity-history'
    },
    FLOW: {
      ROOT: '/dashboard/flow',
      EDIT: (id: string) => `/dashboard/flow/${id}/edit`,
      VIEW: (id: string) => `/dashboard/flow/${id}`
    },
    INVENTORY: {
      ROOT: '/dashboard/inventory',
      BATCH: '/dashboard/inventory?tab=batch',
      BATCH_CREATE: (gtin?: string) => {
        let url = `/dashboard/inventory?tab=batch&createBatch=true`;
        if (gtin) {
          url += `&gtin=${gtin}`;
        }
        return url;
      },
      SUMMARY: '/dashboard/inventory/summary',
      STATISTICS: '/dashboard/inventory/statistics'
    }
  },
  ERROR: {
    FORBIDDEN: '/403'
  }
};
