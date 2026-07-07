import assert from 'node:assert/strict';
import test from 'node:test';

import {
  resolveNotificationHref,
  sanitizeNotificationBody
} from './notification-ui';

test('sanitizeNotificationBody strips local frontend origins from rendered body text', () => {
  assert.equal(
    sanitizeNotificationBody(
      'Status: failed Open: http://localhost:3000/dashboard/campaigns/camp-1/monitor'
    ),
    'Status: failed Open: /dashboard/campaigns/camp-1/monitor'
  );
});

test('resolveNotificationHref maps local deep links to in-app relative routes', () => {
  const href = resolveNotificationHref({
    id: 'n-1',
    event: 'campaign.failed',
    title: 'Campaign failed',
    body: null,
    data: {
      deep_link: 'http://localhost:3000/dashboard/campaigns/camp-1/monitor'
    },
    is_read: false,
    created_at: '2026-07-02T00:00:00Z'
  });

  assert.equal(href, '/dashboard/campaigns/camp-1/monitor');
});
