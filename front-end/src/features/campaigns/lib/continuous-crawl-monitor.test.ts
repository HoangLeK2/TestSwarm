import assert from 'node:assert/strict';
import test from 'node:test';
import {
  boundedCrawlRows,
  campaignVariablesForEditor,
  continuousCrawlPollInterval,
  crawlCompletion,
  isContinuousCrawl,
  mergeCampaignEditorVariables,
  readContinuousCrawlSettings,
  reduceContinuousCrawlProgress,
  updateContinuousCrawlSettings,
  type ContinuousCrawlProgress
} from './continuous-crawl-monitor.ts';

const progress = (overrides: Partial<ContinuousCrawlProgress> = {}) => ({
  campaign_id: 'campaign-1',
  dispatch_id: 'dispatch-1',
  status: 'running' as const,
  health: 'healthy' as const,
  loaded: 20,
  active: 2,
  succeeded: 12,
  failed: 3,
  consecutive_failures: 0,
  exhausted: false,
  generation: 2,
  device_lanes: [],
  recent_targets: [],
  ...overrides
});

test('detects continuous source-pool campaign variables', () => {
  assert.equal(
    isContinuousCrawl({ _crawl: { mode: 'continuous_source_pool' } }),
    true
  );
  assert.equal(isContinuousCrawl({ _crawl: { mode: 'fixed_fan_out' } }), false);
  assert.equal(isContinuousCrawl(null), false);
});

test('completion stays indeterminate until source exhaustion without a cap', () => {
  assert.deepEqual(crawlCompletion(progress()), {
    completed: 15,
    percent: null
  });
  assert.deepEqual(crawlCompletion(progress({ max_targets: 100 })), {
    completed: 15,
    percent: 15
  });
  assert.deepEqual(crawlCompletion(progress({ exhausted: true })), {
    completed: 15,
    percent: 75
  });
});

test('reducer rejects stale generations and timestamps', () => {
  const current = progress({ updated_at: '2026-08-07T12:00:00Z' });
  assert.equal(
    reduceContinuousCrawlProgress(current, progress({ generation: 1 })),
    current
  );
  assert.equal(
    reduceContinuousCrawlProgress(
      current,
      progress({ updated_at: '2026-08-07T11:59:00Z' })
    ),
    current
  );
  const next = progress({ generation: 3, loaded: 30 });
  assert.equal(reduceContinuousCrawlProgress(current, next), next);
});

test('rendered lane and target rows are bounded', () => {
  const rows = boundedCrawlRows(
    progress({
      device_lanes: Array.from({ length: 30 }, (_, i) => ({
        device_serial: `device-${i}`,
        status: 'running' as const,
        completed: i,
        failed: 0
      })),
      recent_targets: Array.from({ length: 30 }, (_, i) => ({
        target_id: `target-${i}`,
        status: 'queued' as const
      }))
    })
  );
  assert.equal(rows.lanes.length, 12);
  assert.equal(rows.targets.length, 8);
});

test('continuous settings preserve internal run metadata and stay typed', () => {
  const original = {
    query: 'jobs',
    _continuous_crawl: { dispatch_id: 'dispatch-1', status: 'completed' },
    _crawl: { mode: 'fixed_fan_out', source_page_size: 250 }
  };
  const configured = updateContinuousCrawlSettings(original, {
    enabled: true
  });

  assert.deepEqual(readContinuousCrawlSettings(configured), {
    enabled: true
  });
  assert.deepEqual(configured._continuous_crawl, original._continuous_crawl);
  assert.equal(
    (configured._crawl as Record<string, unknown>).source_page_size,
    250
  );

  const editorVariables = campaignVariablesForEditor(configured);
  assert.deepEqual(editorVariables, { query: 'jobs' });
  assert.deepEqual(
    mergeCampaignEditorVariables(configured, { query: 'hiring', limit: 10 }),
    { ...configured, query: 'hiring', limit: 10 }
  );
});

test('continuous settings derive devices and targets from assignments', () => {
  const configured = updateContinuousCrawlSettings(
    { _crawl: { max_concurrency: 24, max_targets: 1 } },
    { enabled: true }
  );

  assert.deepEqual(readContinuousCrawlSettings(configured), {
    enabled: true
  });
  const crawl = configured._crawl as Record<string, unknown>;
  assert.equal('max_concurrency' in crawl, false);
  assert.equal('max_targets' in crawl, false);
});

test('polling stops after a terminal status', () => {
  assert.equal(continuousCrawlPollInterval('running'), 5_000);
  assert.equal(continuousCrawlPollInterval('paused'), 5_000);
  assert.equal(continuousCrawlPollInterval('completed'), false);
  assert.equal(continuousCrawlPollInterval('failed'), false);
  assert.equal(continuousCrawlPollInterval(undefined), false);
});
