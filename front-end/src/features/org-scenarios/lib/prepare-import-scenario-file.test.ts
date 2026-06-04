import assert from 'node:assert/strict';
import test from 'node:test';
import { prepareImportScenarioFile } from './prepare-import-scenario-file.ts';

test('prepareImportScenarioFile strips checksum from JSON', async () => {
  const raw = JSON.stringify({
    schema_version: '2.0',
    checksum: 'sha256:deadbeef',
    scenario: { name: 'A', body: { steps: [] } }
  });
  const file = new File([raw], 's.json', { type: 'application/json' });
  const { file: next, strippedChecksum } = await prepareImportScenarioFile(file);
  assert.equal(strippedChecksum, true);
  const parsed = JSON.parse(await next.text()) as Record<string, unknown>;
  assert.equal('checksum' in parsed, false);
  assert.equal((parsed.scenario as { name: string }).name, 'A');
});

test('prepareImportScenarioFile strips checksum line from YAML', async () => {
  const raw = `schema_version: '2.0'
checksum: sha256:abc
scenario:
  name: B
`;
  const file = new File([raw], 's.yaml', { type: 'application/x-yaml' });
  const { file: next, strippedChecksum } = await prepareImportScenarioFile(file);
  assert.equal(strippedChecksum, true);
  const text = await next.text();
  assert.equal(text.includes('checksum:'), false);
  assert.match(text, /name: B/);
});
