import assert from 'node:assert/strict';
import test from 'node:test';

import {
  deviceCapabilityMapFromDevice,
  evaluateNodeCapabilityStatus,
  nodeCapabilityReadiness,
  nodeCapabilityBadgeLabel,
  type NodeCapability
} from './node-capabilities.ts';

const tapImageCapability: NodeCapability = {
  type: 'tap_image',
  group: 'action',
  risk: 'medium',
  requires: ['has_image_match', 'has_opencv'],
  surfaces: ['schema', 'api_schema', 'executor', 'agent_image_match'],
  recorder_evidence: ['template_key', 'match_score', 'match_bounds'],
  inspector_hints: ['show_template_match'],
  description: 'Tap image'
};

test('evaluateNodeCapabilityStatus marks missing runtime capabilities', () => {
  const status = evaluateNodeCapabilityStatus(tapImageCapability, {
    has_image_match: true,
    has_opencv: false
  });

  assert.equal(status.ok, false);
  assert.deepEqual(status.missing, ['has_opencv']);
  assert.deepEqual(status.unknown, []);
  assert.equal(nodeCapabilityBadgeLabel(status), 'missing has_opencv');
});

test('evaluateNodeCapabilityStatus keeps unknown capabilities separate', () => {
  const status = evaluateNodeCapabilityStatus(tapImageCapability, {
    has_image_match: true
  });

  assert.equal(status.ok, true);
  assert.deepEqual(status.missing, []);
  assert.deepEqual(status.unknown, ['has_opencv']);
  assert.equal(nodeCapabilityBadgeLabel(status), 'unknown has_opencv');
});

test('nodeCapabilityBadgeLabel summarizes satisfied requirements', () => {
  const status = evaluateNodeCapabilityStatus(tapImageCapability, {
    has_image_match: true,
    has_opencv: true
  });

  assert.equal(status.ok, true);
  assert.equal(status.risk, 'medium');
  assert.equal(
    nodeCapabilityBadgeLabel(status),
    'medium · has_image_match, has_opencv'
  );
});

test('nodeCapabilityReadiness returns a compact UI status', () => {
  assert.equal(
    nodeCapabilityReadiness(tapImageCapability, {
      has_image_match: true,
      has_opencv: true
    }).kind,
    'ready'
  );
  assert.equal(
    nodeCapabilityReadiness(tapImageCapability, {
      has_image_match: true,
      has_opencv: false
    }).kind,
    'missing'
  );
  assert.equal(
    nodeCapabilityReadiness(tapImageCapability, {
      has_image_match: true
    }).kind,
    'unknown'
  );
  assert.equal(
    nodeCapabilityReadiness({ ...tapImageCapability, requires: [] }, {}).kind,
    'none'
  );
});

test('deviceCapabilityMapFromDevice merges explicit capability maps', () => {
  const caps = deviceCapabilityMapFromDevice({
    capabilities: { has_ocr: true, has_tesseract: false },
    has_image_match: true
  });

  assert.deepEqual(caps, {
    has_ocr: true,
    has_tesseract: false,
    has_image_match: true
  });
});

test('deviceCapabilityMapFromDevice derives u2 based requirements from live device fields', () => {
  const caps = deviceCapabilityMapFromDevice({
    u2_ready: true,
    touch_method: 'u2'
  });

  assert.deepEqual(caps, {
    has_u2: true,
    supports_advanced_gestures: true
  });
});

test('deviceCapabilityMapFromDevice leaves unsupported frontend-only facts unknown', () => {
  const caps = deviceCapabilityMapFromDevice({
    serial: 'SN-1',
    model: 'Pixel'
  });

  assert.equal(caps, undefined);
});
