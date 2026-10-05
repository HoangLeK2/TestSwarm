import assert from 'node:assert/strict';
import test from 'node:test';

import { buildControlRecordPageSummary } from './control-record-page-summary.ts';
import { mergeCampaignScenarioVariables } from '../../../components/device-vars-json-model.ts';

test('summarizes configured multi-page campaign targets', () => {
  const summary = buildControlRecordPageSummary(
    {
      PAGE_COUNT: 2,
      PAGE_TARGETS: ['Go2Joy Vietnam', 'Booking.com'],
      PAGE_ROW_TEXTS: ['Go2Joy Vietnam', 'Booking.com']
    },
    true,
    'Nuôi Instagram - Kết bạn từ bài post Home đúng keyword 1 — chiến dịch',
    ['PAGE_COUNT', 'PAGE_TARGETS', 'PAGE_ROW_TEXTS']
  );

  assert.equal(summary?.label, '2 page: Go2Joy Vietnam, Booking.com');
  assert.equal(summary?.targetType, 'page');
  assert.equal(summary?.targetInputKind, 'manual');
  assert.equal(
    summary?.contextLabel,
    'Campaign: Nuôi Instagram - Kết bạn từ bài post Home đúng keyword 1 — chiến dịch: 2 page: Go2Joy Vietnam, Booking.com'
  );
  assert.deepEqual(summary?.bindingKeys, [
    'PAGE_COUNT',
    'PAGE_TARGETS',
    'PAGE_ROW_TEXTS'
  ]);
  assert.deepEqual(summary?.unusedBindingKeys, []);
  assert.equal(summary?.usageWarning, undefined);
  assert.equal(summary?.warning, undefined);
});

test('summarizes configured multi-group campaign targets', () => {
  const summary = buildControlRecordPageSummary(
    {
      GROUP_COUNT: 2,
      GROUP_SEARCHES: ['OpenClaw VN', 'AI Agents VN'],
      GROUP_ROW_TEXTS: ['OpenClaw VN', 'AI Agents VN']
    },
    true,
    'Group nurture campaign',
    ['GROUP_COUNT', 'GROUP_SEARCHES', 'GROUP_ROW_TEXTS']
  );

  assert.equal(summary?.targetType, 'group');
  assert.equal(summary?.targetInputKind, 'manual');
  assert.equal(summary?.label, '2 group: OpenClaw VN, AI Agents VN');
  assert.deepEqual(summary?.unusedBindingKeys, []);
  assert.equal(summary?.usageWarning, undefined);
});

test('summarizes target-form group selections for multi-group flows', () => {
  const summary = buildControlRecordPageSummary(
    {
      GROUP_COUNT: 2,
      GROUP_TARGET_IDS: ['group-1', 'group-2'],
      GROUP_TARGETS: ['OpenClaw VN', 'AI Agents VN'],
      GROUP_SEARCHES: ['OpenClaw VN', 'AI Agents VN'],
      GROUP_ROW_TEXTS: ['OpenClaw VN', 'AI Agents VN'],
      _target_form: {
        platform: 'instagram',
        selected: {
          group: [
            {
              id: 'group-1',
              display_name: 'OpenClaw VN',
              entity_type: 'group',
              platform: 'instagram'
            },
            {
              id: 'group-2',
              display_name: 'AI Agents VN',
              entity_type: 'group',
              platform: 'instagram'
            }
          ],
          page: [],
          profile: []
        }
      }
    },
    true,
    'Group nurture campaign',
    ['GROUP_COUNT', 'GROUP_SEARCHES', 'GROUP_ROW_TEXTS']
  );

  assert.equal(summary?.label, '2 group: OpenClaw VN, AI Agents VN');
  assert.equal(summary?.targetInputKind, 'catalog');
  assert.deepEqual(summary?.usedBindingKeys, [
    'GROUP_COUNT',
    'GROUP_SEARCHES',
    'GROUP_ROW_TEXTS'
  ]);
  assert.deepEqual(summary?.unusedBindingKeys, ['GROUP_TARGETS']);
});

test('summarizes single-page scenario defaults', () => {
  const summary = buildControlRecordPageSummary(
    {
      PAGE_COUNT: 1,
      PAGE_TARGETS: ['ten fanpage'],
      PAGE_ROW_TEXTS: ['Tên Fanpage']
    },
    false
  );

  assert.equal(summary?.contextLabel, 'Scenario mặc định: 1 page: ten fanpage');
});

test('uses campaign overrides after scenario defaults are merged', () => {
  const scenarioDefaults = {
    PAGE_COUNT: 1,
    PAGE_TARGETS: ['ten fanpage'],
    PAGE_ROW_TEXTS: ['Tên Fanpage']
  };
  const campaignVariables = {
    PAGE_COUNT: 2,
    PAGE_TARGETS: ['Go2Joy Vietnam', 'Booking.com'],
    PAGE_ROW_TEXTS: ['Go2Joy Vietnam', 'Booking.com']
  };

  const summary = buildControlRecordPageSummary(
    mergeCampaignScenarioVariables(campaignVariables, scenarioDefaults),
    true
  );

  assert.deepEqual(summary?.labels, ['Go2Joy Vietnam', 'Booking.com']);
});

test('warns when page count exceeds configured targets', () => {
  const summary = buildControlRecordPageSummary(
    {
      PAGE_COUNT: 2,
      PAGE_TARGETS: ['Go2Joy Vietnam']
    },
    true
  );

  assert.equal(summary?.label, '2 page: Go2Joy Vietnam, Chưa cấu hình page 2');
  assert.equal(summary?.warning, 'Thiếu cấu hình 1 page');
});

test('warns when configured campaign targets are not referenced by the flow', () => {
  const summary = buildControlRecordPageSummary(
    {
      PAGE_COUNT: 2,
      PAGE_TARGETS: ['Go2Joy Vietnam', 'Booking.com']
    },
    true,
    'Home keyword campaign',
    ['POST_KEYWORDS', 'PROFILE_REQUIRED_KEYWORDS']
  );

  assert.deepEqual(summary?.usedBindingKeys, []);
  assert.deepEqual(summary?.unusedBindingKeys, ['PAGE_COUNT', 'PAGE_TARGETS']);
  assert.equal(
    summary?.usageWarning,
    'Đã cấu hình target nhưng flow hiện tại chưa dùng các biến này'
  );
});
