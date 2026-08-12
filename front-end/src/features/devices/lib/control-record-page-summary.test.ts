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
    true
  );

  assert.equal(summary?.label, '2 page: Go2Joy Vietnam, Booking.com');
  assert.equal(
    summary?.contextLabel,
    'Campaign đang áp dụng: 2 page: Go2Joy Vietnam, Booking.com'
  );
  assert.equal(summary?.warning, undefined);
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
