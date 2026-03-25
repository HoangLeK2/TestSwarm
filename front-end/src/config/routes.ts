export const ROUTES = {
  AUTH: {
    SIGN_IN: '/auth/sign-in',
    SIGN_UP: '/auth/sign-up',
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
    CONTROL_RECORD: '/dashboard/device-farm/control',
    /** Điều khiển thiết bị với serial đã chọn (để vào đúng màn hình rồi lấy XML). */
    CONTROL_RECORD_WITH_SERIAL: (serial: string) =>
      `/dashboard/device-farm/control?serial=${encodeURIComponent(serial)}`
  },
  CAMPAIGNS: {
    ROOT: '/dashboard/campaigns',
    DETAIL: (id: string) => `/dashboard/campaigns/${id}`
  },
  DASHBOARD: {
    ROOT: '/dashboard',
    ORGANIZATION: '/dashboard/settings/organization',
    ORGANIZATION_MEMBER: (id: string) => `/dashboard/org/${id}/member`,
    ORGANIZATION_SETTINGS: (id: string) => `/dashboard/org/${id}`,
    ORGANIZATION_EDIT: (id: string) => `/dashboard/settings/organization/${id}`,
    API_KEYS: (id: string) => `/dashboard/org/${id}/api-keys`,
    TOTP: (id: string) => `/dashboard/org/${id}/totp`,
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
    },
    SETTINGS: {
      ORGANIZATION: '/dashboard/settings',
      API_KEYS: '/dashboard/settings/api-keys',
      TOTP: '/dashboard/settings/totp'
    }
  },
  ERROR: {
    FORBIDDEN: '/403'
  }
};
