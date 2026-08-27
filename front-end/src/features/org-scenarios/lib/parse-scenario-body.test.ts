import assert from 'node:assert/strict';
import test from 'node:test';
import {
  countPreviewSteps,
  extractPreviewSteps
} from './parse-scenario-body.ts';

test('extractPreviewSteps keeps flat fields when config is empty (post-save API shape)', () => {
  const steps = extractPreviewSteps({
    steps: [
      {
        id: 's-1',
        type: 'if_element',
        config: {},
        by: 'description',
        value: 'Tìm kiếm',
        then: [
          {
            id: 's-1-then-1',
            type: 'tap_selector',
            config: {},
            by: 'description',
            value: 'Tìm kiếm'
          }
        ],
        else: []
      }
    ]
  });
  assert.equal(steps.length, 1);
  assert.equal(steps[0].type, 'if_element');
  assert.equal((steps[0] as { by?: string }).by, 'description');
  assert.equal((steps[0] as { value?: string }).value, 'Tìm kiếm');
  const then = (steps[0] as { then?: { by?: string; value?: string }[] }).then;
  assert.ok(Array.isArray(then) && then.length === 1);
  assert.equal(then[0].by, 'description');
  assert.equal(then[0].value, 'Tìm kiếm');
});

test('extractPreviewSteps unwraps non-empty type+config DSL steps', () => {
  const steps = extractPreviewSteps({
    steps: [
      {
        id: 'dsl-1',
        type: 'interaction.tap',
        config: { by: 'text', value: 'OK', timeout: 5 }
      }
    ]
  });
  assert.equal(steps.length, 1);
  assert.equal(steps[0].type, 'interaction.tap');
  assert.equal((steps[0] as { by?: string }).by, 'text');
  assert.equal((steps[0] as { value?: string }).value, 'OK');
  assert.equal((steps[0] as { timeout?: number }).timeout, 5);
});

test('countPreviewSteps includes nested branch, loop, and branch-list steps', () => {
  const steps = extractPreviewSteps({
    steps: [
      {
        type: 'if_variable',
        name: 'READY',
        then: [
          {
            type: 'loop',
            count: 2,
            steps: [
              { type: 'tap_selector', by: 'text', value: 'OK' },
              {
                type: 'random_branch',
                branches: [
                  {
                    id: 'a',
                    steps: [{ type: 'wait', seconds: 1 }]
                  }
                ]
              }
            ]
          }
        ],
        else: [{ type: 'wait', seconds: 0.1 }]
      }
    ]
  });

  assert.deepEqual(countPreviewSteps(steps), {
    topLevel: 1,
    total: 6
  });
});
