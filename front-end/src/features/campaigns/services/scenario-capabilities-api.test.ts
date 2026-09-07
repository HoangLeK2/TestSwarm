import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  scenarioCapabilityIssueSummary,
  scenarioCapabilityWarningSummary
} from '../lib/scenario-capability-preflight';

test('scenario capability api exposes live device capability and preflight endpoints', () => {
  const source = readFileSync(new URL('./api.ts', import.meta.url), 'utf8');

  assert.match(source, /scenarioDeviceCapabilitiesApi/);
  assert.match(
    source,
    /\/scenario\/device-capabilities\/\$\{encodeURIComponent\(serial\)\}/
  );
  assert.match(
    source,
    /\/scenario\/preflight\/\$\{encodeURIComponent\(serial\)\}/
  );
  assert.match(source, /\.post<ScenarioCapabilityPreflightOut>/);
  assert.match(source, /\{ scenario \}/);
});

test('scenario device capability hook polls by serial', () => {
  const source = readFileSync(
    new URL('../hooks/use-campaigns.ts', import.meta.url),
    'utf8'
  );

  assert.match(source, /useScenarioDeviceCapabilities/);
  assert.match(
    source,
    /scenarioDeviceCapabilitiesApi\.get\(normalizedSerial\)/
  );
  assert.match(source, /refetchInterval: 15_000/);
});

test('scenario capability preflight helper summarizes blocking issues', () => {
  const summary = scenarioCapabilityIssueSummary({
    ok: false,
    issues: [
      {
        path: 'steps[0]',
        index: 0,
        step_type: 'extract_text_ocr',
        missing: ['has_ocr', 'has_tesseract'],
        risk: 'blocked'
      },
      {
        path: 'steps[1]',
        index: 1,
        step_type: 'find_image',
        missing: ['has_image_match'],
        risk: 'blocked'
      },
      {
        path: 'steps[2]',
        index: 2,
        step_type: 'tap_image',
        missing: ['has_opencv'],
        risk: 'blocked'
      }
    ],
    warnings: []
  });

  assert.equal(
    summary,
    'steps[0] extract_text_ocr: has_ocr, has_tesseract; steps[1] find_image: has_image_match; +1 more'
  );
});

test('scenario capability preflight helper summarizes unknown warnings', () => {
  const summary = scenarioCapabilityWarningSummary({
    ok: true,
    issues: [],
    warnings: [
      {
        path: 'steps[0]',
        index: 0,
        step_type: 'swipe_ratio',
        unknown: ['supports_advanced_gestures']
      }
    ]
  });

  assert.equal(summary, 'steps[0] swipe_ratio: supports_advanced_gestures');
});

test('scenario capability preflight messages exist for en and vi', () => {
  for (const locale of ['en', 'vi']) {
    const messages = JSON.parse(
      readFileSync(
        new URL(`../../../../messages/${locale}.json`, import.meta.url),
        'utf8'
      )
    );
    const node = messages.campaignsFeature?.capabilityPreflight;
    assert.equal(typeof node?.checkingTitle, 'string');
    assert.equal(typeof node?.stepBlockedToast, 'string');
    assert.equal(typeof node?.campaignBlockedToast, 'string');
    assert.equal(typeof node?.summaryMore, 'string');
  }
});

test('scenario dialog runs capability preflight before preview stream', () => {
  const source = readFileSync(
    new URL('../components/scenario-dialog.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /ensureScenarioCapabilityPreflight/);
  assert.match(source, /campaignsFeature\.capabilityPreflight/);
  assert.match(source, /scenarioDeviceCapabilitiesApi\.preflight/);
  assert.match(source, /if \(!preflightOk\) return/);
  assert.match(source, /stepBlockedTitle/);
  assert.doesNotMatch(source, /Preflight capability chặn chạy/);
});

test('control record view runs capability preflight before inline preview stream', () => {
  const source = readFileSync(
    new URL(
      '../../devices/components/control-record-view.tsx',
      import.meta.url
    ),
    'utf8'
  );

  assert.match(source, /ensureScenarioCapabilityPreflight/);
  assert.match(source, /campaignsFeature\.capabilityPreflight/);
  assert.match(source, /scenarioDeviceCapabilitiesApi\.preflight/);
  assert.match(source, /if \(!preflightOk\)/);
  assert.match(source, /stepBlockedTitle/);
  assert.doesNotMatch(source, /Preflight capability chặn chạy/);
});

test('run campaign dialog blocks campaign dispatch when capability preflight fails', () => {
  const source = readFileSync(
    new URL('../components/run-campaign-dialog.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /runCapabilityPreflight/);
  assert.match(source, /campaignsFeature\.capabilityPreflight/);
  assert.match(source, /scenarioDeviceCapabilitiesApi\.preflight/);
  assert.match(
    source,
    /if \(!\(await runCapabilityPreflight\(serials\)\)\) return/
  );
  assert.match(source, /campaignBlockedTitle/);
  assert.doesNotMatch(source, /Preflight campaign chặn chạy/);
});
