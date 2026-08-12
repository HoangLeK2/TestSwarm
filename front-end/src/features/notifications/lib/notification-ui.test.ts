import assert from 'node:assert/strict';
import test from 'node:test';

import {
  collapseRepeatedDeviceDisconnects,
  resolveNotificationHref,
  sanitizeNotificationBody
} from './notification-ui';

test('collapseRepeatedDeviceDisconnects groups the same device within four days', () => {
  const items = [
    {
      id: 'new',
      event: 'device.disconnect',
      title: 'offline',
      body: null,
      data: { serial: 'SER-1' },
      is_read: true,
      created_at: '2026-08-09T00:00:00Z'
    },
    {
      id: 'old',
      event: 'device.disconnect',
      title: 'offline',
      body: null,
      data: { serial: 'SER-1' },
      is_read: false,
      created_at: '2026-08-07T00:00:00Z'
    }
  ] as never;

  const grouped = collapseRepeatedDeviceDisconnects(items);

  assert.equal(grouped.length, 1);
  assert.equal(grouped[0].data.occurrence_count, 2);
  assert.deepEqual(grouped[0].data.grouped_notification_ids, ['new', 'old']);
  assert.equal(grouped[0].is_read, false);
});

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
  } as never);

  assert.equal(href, '/dashboard/campaigns/camp-1/monitor');
});
