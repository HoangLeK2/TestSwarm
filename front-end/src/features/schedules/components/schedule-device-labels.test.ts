import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveScheduleDeviceLabels } from './schedule-device-labels.ts';

test('resolves every selected schedule device to its friendly name', () => {
  const selectedSerials = [
    '29e4524a003f7ece',
    '988a1c44514951394f',
    'ce021712734c1a2502',
    'mh11-serial',
    'mh13-serial'
  ];
  const currentPage = [
    { serial: 'mh11-serial', name: 'MH11' },
    { serial: 'mh13-serial', name: 'MH13' }
  ];
  const allDevices = [
    { serial: '29e4524a003f7ece', name: 'MH1' },
    { serial: '988a1c44514951394f', name: 'MH2' },
    { serial: 'ce021712734c1a2502', name: 'MH3' },
    ...currentPage
  ];

  const labels = resolveScheduleDeviceLabels(
    selectedSerials,
    currentPage,
    allDevices
  );

  assert.deepEqual(
    labels,
    new Map([
      ['29e4524a003f7ece', 'MH1'],
      ['988a1c44514951394f', 'MH2'],
      ['ce021712734c1a2502', 'MH3'],
      ['mh11-serial', 'MH11'],
      ['mh13-serial', 'MH13']
    ])
  );
});

test('falls back to the serial only when a device has no friendly name', () => {
  const labels = resolveScheduleDeviceLabels(
    ['known-without-name', 'missing'],
    [{ serial: 'known-without-name', name: '' }],
    []
  );

  assert.deepEqual(
    labels,
    new Map([
      ['known-without-name', 'known-without-name'],
      ['missing', 'missing']
    ])
  );
});

test('does not replace a friendly name with an empty page result', () => {
  const labels = resolveScheduleDeviceLabels(
    ['mh1-serial'],
    [{ serial: 'mh1-serial', name: '' }],
    [{ serial: 'mh1-serial', name: 'MH1' }]
  );

  assert.equal(labels.get('mh1-serial'), 'MH1');
});
