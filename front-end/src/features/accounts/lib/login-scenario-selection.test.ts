import assert from 'node:assert/strict';
import test from 'node:test';
import {
  accountLoginOrgScenarioName,
  accountLoginOrgScenarioTags,
  pickOrgLoginScenario,
  resolveLoginScenarioSource
} from './login-scenario-selection.ts';

test('prefers an active org login override over system template fallback', () => {
  const orgScenario = {
    id: 'org-login',
    status: 'active',
    is_runnable: true,
    tags: [
      'login',
      'instagram',
      'account-login',
      'login-override',
      'system-account-login'
    ],
    updated_at: '2026-09-16T10:00:00Z'
  };
  const source = resolveLoginScenarioSource({
    orgScenario,
    orgBody: { body_json: { steps: [{ type: 'login_if_needed' }] } },
    template: { id: 'template-login', steps: [{ type: 'wait' }] }
  });

  assert.deepEqual(source, {
    kind: 'org',
    scenarioId: 'org-login',
    steps: [{ type: 'login_if_needed' }]
  });
});

test('falls back to the system template when no org login scenario exists', () => {
  const source = resolveLoginScenarioSource({
    orgScenario: null,
    orgBody: null,
    template: { id: 'template-login', steps: [{ type: 'login_if_needed' }] }
  });

  assert.deepEqual(source, {
    kind: 'template',
    templateId: 'template-login',
    steps: [{ type: 'login_if_needed' }]
  });
});

test('selects active login scenario by platform tag and ignores drafts', () => {
  const scenario = pickOrgLoginScenario(
    [
      {
        id: 'draft-login',
        kind: 'sequence',
        status: 'draft',
        is_runnable: true,
        tags: ['login', 'instagram'],
        updated_at: '2026-09-16T12:00:00Z'
      },
      {
        id: 'active-login',
        kind: 'sequence',
        status: 'active',
        is_runnable: true,
        tags: [
          'login',
          'login-platform:instagram',
          'account-login',
          'login-override',
          'system-account-login'
        ],
        updated_at: '2026-09-16T10:00:00Z'
      }
    ],
    'instagram'
  );

  assert.equal(scenario?.id, 'active-login');
});

test('ignores graph login scenarios because account login runs sequence steps', () => {
  const scenario = pickOrgLoginScenario(
    [
      {
        id: 'graph-login',
        kind: 'graph',
        status: 'active',
        is_runnable: true,
        tags: [
          'login',
          'instagram',
          'account-login',
          'login-override',
          'system-account-login'
        ],
        updated_at: '2026-09-16T12:00:00Z'
      },
      {
        id: 'sequence-login',
        kind: 'sequence',
        status: 'active',
        is_runnable: true,
        tags: [
          'login',
          'instagram',
          'account-login',
          'login-override',
          'system-account-login'
        ],
        updated_at: '2026-09-16T10:00:00Z'
      }
    ],
    'instagram'
  );

  assert.equal(scenario?.id, 'sequence-login');
});

test('prefers explicit account-login override tags over a plain clone', () => {
  const scenario = pickOrgLoginScenario(
    [
      {
        id: 'plain-clone',
        kind: 'sequence',
        status: 'active',
        is_runnable: true,
        tags: ['login', 'instagram'],
        updated_at: '2026-09-16T12:00:00Z'
      },
      {
        id: 'override',
        kind: 'sequence',
        status: 'active',
        is_runnable: true,
        tags: [
          'login',
          'instagram',
          'account-login',
          'login-override',
          'system-account-login'
        ],
        updated_at: '2026-09-16T10:00:00Z'
      }
    ],
    'instagram'
  );

  assert.equal(scenario?.id, 'override');
});

test('falls back to the system template when org override body has no steps', () => {
  const source = resolveLoginScenarioSource({
    orgScenario: {
      id: 'org-login',
      kind: 'sequence',
      status: 'active',
      tags: [
        'login',
        'instagram',
        'account-login',
        'login-override',
        'system-account-login'
      ]
    },
    orgBody: { body_json: { steps: [] } },
    template: { id: 'template-login', steps: [{ type: 'login_if_needed' }] }
  });

  assert.deepEqual(source, {
    kind: 'template',
    templateId: 'template-login',
    steps: [{ type: 'login_if_needed' }]
  });
});

test('ignores active login scenarios that were not system-created for Account Login', () => {
  const scenario = pickOrgLoginScenario(
    [
      {
        id: 'manual-active-login',
        kind: 'sequence',
        status: 'active',
        is_runnable: true,
        tags: ['login', 'instagram', 'account-login', 'login-override'],
        updated_at: '2026-09-16T12:00:00Z'
      }
    ],
    'instagram'
  );

  assert.equal(scenario, null);
});

test('accountLoginOrgScenarioTags adds explicit system-created override tags once', () => {
  assert.deepEqual(
    accountLoginOrgScenarioTags('instagram,login', 'instagram'),
    [
      'instagram',
      'login',
      'login-platform:instagram',
      'account-login',
      'login-override',
      'system-account-login'
    ]
  );
});

test('accountLoginOrgScenarioName uses display name before internal name', () => {
  assert.equal(
    accountLoginOrgScenarioName({
      name: 'instagram_login',
      display_name: 'Đăng nhập Instagram'
    }),
    'Đăng nhập Instagram (Account Login)'
  );
});
