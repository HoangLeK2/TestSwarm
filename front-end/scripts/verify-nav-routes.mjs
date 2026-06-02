#!/usr/bin/env node
/**
 * Ensures every path in dashboard-nav.ts has a matching Next.js page under app/[locale]/.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appLocale = path.join(root, 'src/app/[locale]');

/** Keep in sync with DASHBOARD_NAV_PATHS in src/config/dashboard-nav.ts */
const NAV_PATHS = [
  '/dashboard/device-farm',
  '/dashboard/devices',
  '/dashboard/device-farm/control',
  '/dashboard/device-groups',
  '/dashboard/campaigns',
  '/dashboard/schedules',
  '/dashboard/accounts',
  '/dashboard/device-farm/account-groups',
  '/dashboard/scenario-templates',
  '/dashboard/content',
  '/dashboard/analytics',
  '/dashboard/activity-history',
  '/dashboard/notifications',
  '/dashboard/settings/organization',
  '/dashboard/settings/organization/members',
  '/dashboard/relay-agents'
];

function pageExists(routePath) {
  const rel = routePath.replace(/^\//, '');
  const asPage = path.join(appLocale, rel, 'page.tsx');
  const asFile = path.join(appLocale, `${rel}.tsx`);
  return fs.existsSync(asPage) || fs.existsSync(asFile);
}

let failed = 0;
for (const p of NAV_PATHS) {
  if (!pageExists(p)) {
    console.error(`MISSING page for nav path: ${p}`);
    failed++;
  }
}

if (failed > 0) {
  process.exit(1);
}

console.log(`OK: ${NAV_PATHS.length} dashboard nav paths have pages.`);
