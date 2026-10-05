import assert from 'node:assert/strict';
import test from 'node:test';

import { isDeviceTargetFormControlledKey } from './device-vars-target-form-model.ts';

test('target form exposes generated keys reserved by the generic variable editor', () => {
  assert.equal(isDeviceTargetFormControlledKey('_target_form'), true);
  assert.equal(isDeviceTargetFormControlledKey('TARGET_ENTITY_ID'), true);
  assert.equal(isDeviceTargetFormControlledKey('GROUP_TARGETS'), true);
  assert.equal(isDeviceTargetFormControlledKey('custom_note'), false);
});
