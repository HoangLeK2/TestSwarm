import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  getRelayConnectionState,
  getVisibleRelaySerials,
  isRelayOperational,
  type RelayConnectionState
} from './relay-agent-status.ts';

const here = dirname(fileURLToPath(import.meta.url));
const messagesDir = join(here, '../../../../messages');

function loadMessages(locale: 'en' | 'vi') {
  return JSON.parse(readFileSync(join(messagesDir, `${locale}.json`), 'utf8'));
}

const STATES: RelayConnectionState[] = ['inactive', 'connecting', 'connected'];

test('relay connection status i18n exists in en and vi', () => {
  for (const locale of ['en', 'vi'] as const) {
    const messages = loadMessages(locale);
    for (const state of STATES) {
      const label = messages.relayAgentsFeature?.connectionStatus?.[state];
      assert.ok(
        typeof label === 'string' && label.trim().length > 0,
        `${locale}.relayAgentsFeature.connectionStatus.${state}`
      );
    }
    assert.match(messages.relayAgentsFeature.onlineSummary, /\{connected\}/);
  }
});

test('getRelayConnectionState resolves inactive, connecting, and connected', () => {
  const now = Date.now();
  const agent = {
    relay_id: 'relay-1',
    hostname: 'host',
    ip: '127.0.0.1',
    version: '1',
    serials: [],
    status: 'online' as const,
    connected_at: new Date(now - 120_000).toISOString(),
    last_heartbeat_at: new Date(now - 5_000).toISOString(),
    disconnected_at: null
  };

  assert.equal(getRelayConnectionState(agent), 'connected');
  assert.equal(isRelayOperational('connected'), true);

  assert.equal(
    getRelayConnectionState({
      ...agent,
      status: 'offline',
      disconnected_at: new Date(now).toISOString()
    }),
    'inactive'
  );

  assert.equal(
    getRelayConnectionState({
      ...agent,
      connected_at: new Date(now - 5_000).toISOString()
    }),
    'connecting'
  );

  assert.equal(getRelayConnectionState(agent, { busy: true }), 'connecting');
});

test('getVisibleRelaySerials returns serials only when connected', () => {
  const now = Date.now();
  const agent = {
    relay_id: 'relay-1',
    hostname: 'host',
    ip: '127.0.0.1',
    version: '1',
    serials: ['dev-1', 'pending-x'],
    status: 'online' as const,
    live_connected: true,
    connected_at: new Date(now - 120_000).toISOString(),
    last_heartbeat_at: new Date(now - 5_000).toISOString(),
    disconnected_at: null
  };

  assert.deepEqual(getVisibleRelaySerials(agent), ['dev-1']);
  assert.deepEqual(
    getVisibleRelaySerials({
      ...agent,
      live_connected: false,
      status: 'offline',
      disconnected_at: new Date(now).toISOString()
    }),
    []
  );
});
