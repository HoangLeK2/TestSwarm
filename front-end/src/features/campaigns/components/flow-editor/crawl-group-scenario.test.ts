import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import type { FlowStep } from '../scenario-steps/types';
import {
  countStepTypes,
  resolveStepAtPath,
  updateStepAtPath,
  walkFlowStepsWithPaths
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-tree-walk.ts';
import {
  findStepByFlowgramId,
  patchStepByFlowgramId
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from '../../../scenario-templates/components/scenario-flow-editor/patch-step-tree.ts';

const __dir = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dir, '../../../../../../');

function loadJsonSteps(relativePath: string): FlowStep[] {
  const raw = JSON.parse(
    readFileSync(join(REPO_ROOT, relativePath), 'utf8')
  ) as Record<string, unknown>;
  const steps =
    raw.steps ??
    ((raw.scenario as Record<string, unknown>)?.body as Record<string, unknown>)
      ?.steps;
  assert.ok(Array.isArray(steps), `expected steps[] in ${relativePath}`);
  return steps as FlowStep[];
}

function assertAllStepsHaveType(steps: FlowStep[], label: string): void {
  for (const visit of walkFlowStepsWithPaths(steps)) {
    assert.ok(
      typeof visit.step.type === 'string' && visit.step.type.length > 0,
      `${label}: step at depth ${visit.depth} missing type`
    );
  }
}

const FB_GROUP_STEPS = loadJsonSteps(
  'device_farm/scenarios/fb_group_crawl.json'
);
const CRAWL_GROUP_STEPS = loadJsonSteps(
  'front-end/src/features/campaigns/components/flow-editor/fixtures/crawl-group-3.json'
);

const REQUIRED_CRAWL_TYPES = [
  'loop',
  'extract',
  'social_find_comment_button',
  'social_tap_comment_target',
  'social_apply_comment_filter',
  'if_element',
  'scroll_down',
  'key',
  'tap_selector',
  'input_text'
] as const;

test('crawl fixtures have well-formed step types', () => {
  assertAllStepsHaveType(FB_GROUP_STEPS, 'fb_group_crawl');
  assertAllStepsHaveType(CRAWL_GROUP_STEPS, 'crawl group 3');
});

test('crawl fixtures contain comment crawl node chain', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const types = countStepTypes(steps);
    assert.ok(
      types.get('social_find_comment_button')! >= 1,
      'missing social_find_comment_button'
    );
    assert.ok(
      types.get('social_tap_comment_target')! >= 1,
      'missing social_tap_comment_target'
    );
    assert.ok(
      types.get('social_apply_comment_filter')! >= 1,
      'missing social_apply_comment_filter'
    );
    assert.equal(
      types.get('social_open_comments') ?? 0,
      0,
      'template should not use legacy comment node'
    );
    const commentExtracts = walkFlowStepsWithPaths(steps).filter(
      (v) => v.step.type === 'extract' && v.step.entity === 'comments'
    );
    assert.ok(commentExtracts.length >= 1, 'missing extract entity=comments');
    assert.ok(types.get('extract')! >= 2, 'expected post + comment extract');
    for (const req of REQUIRED_CRAWL_TYPES) {
      assert.ok(types.get(req)! >= 1, `missing step type ${req}`);
    }
  }
});

test('every nested step is reachable via resolveStepAtPath', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    for (const visit of walkFlowStepsWithPaths(steps)) {
      const resolved = resolveStepAtPath(steps, visit.path);
      assert.ok(
        resolved,
        `unresolved path depth=${visit.depth} type=${visit.step.type}`
      );
      assert.equal(resolved.type, visit.step.type);
    }
  }
});

test('comments extract fields round-trip through updateStepAtPath', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const extracts = walkFlowStepsWithPaths(steps).filter(
      (v) => v.step.type === 'extract' && v.step.entity === 'comments'
    );
    assert.ok(extracts.length >= 1);
    for (const { step, path } of extracts) {
      const edited = {
        ...step,
        max_items: 99,
        comment_scroll_passes: 7
      } as FlowStep;
      const next = updateStepAtPath(steps, path, edited);
      const updated = resolveStepAtPath(next, path);
      assert.ok(updated);
      assert.equal(updated.max_items, 99);
      assert.equal(updated.comment_scroll_passes, 7);
    }
  }
});

test('split comment sequence keeps editable comments extract as a normal step', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const commentExtract = walkFlowStepsWithPaths(steps).find(
      (v) => v.step.type === 'extract' && v.step.entity === 'comments'
    );
    assert.ok(commentExtract, 'missing entity=comments extract');
    const edited = {
      ...commentExtract.step,
      max_items: 66
    } as FlowStep;
    const next = updateStepAtPath(steps, commentExtract.path, edited);
    const updated = resolveStepAtPath(next, commentExtract.path);
    assert.ok(updated);
    assert.equal(updated.max_items, 66);
  }
});

test('patchStepByFlowgramId updates nested extract when _fgId is present', () => {
  const loop = CRAWL_GROUP_STEPS.find((s) => s.type === 'loop');
  assert.ok(loop);
  const body = (loop as FlowStep & { steps?: FlowStep[] }).steps ?? [];
  const extractIdx = body.findIndex(
    (s) => s.type === 'extract' && s.entity === 'comments'
  );
  assert.ok(extractIdx >= 0);
  const extract = body[extractIdx]!;
  const fgId = 'perf-extract-fg';
  const stepsWithFg = CRAWL_GROUP_STEPS.map((s) =>
    s.type === 'loop'
      ? ({
          ...s,
          steps: body.map((c, i) =>
            i === extractIdx ? { ...c, _fgId: fgId } : c
          )
        } as FlowStep)
      : s
  );
  const next = patchStepByFlowgramId(stepsWithFg, fgId, {
    ...extract,
    max_items: 200,
    comment_scroll_passes: 20
  } as FlowStep);
  const found = findStepByFlowgramId(next, fgId);
  assert.ok(found);
  assert.equal(found.max_items, 200);
  assert.equal(found.comment_scroll_passes, 20);
});

test('comment extract contract: dedupe_field and require_verified_parent', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const extracts = walkFlowStepsWithPaths(steps).filter(
      (v) => v.step.type === 'extract' && v.step.entity === 'comments'
    );
    for (const { step } of extracts) {
      assert.equal(step.dedupe_field, 'comment_key');
      if (step.require_verified_parent != null) {
        assert.equal(step.require_verified_parent, true);
      }
    }
  }
});

test('post extract stays before split comment sequence inside loop (no back before comments)', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const loop = steps.find((s) => s.type === 'loop') as FlowStep & {
      steps?: FlowStep[];
    };
    assert.ok(loop?.steps?.length);
    const body = loop.steps!;
    const postIdx = body.findIndex(
      (s) => s.type === 'extract' && s.entity === 'posts'
    );
    const findIdx = body.findIndex(
      (s) => s.type === 'social_find_comment_button'
    );
    const tapIdx = body.findIndex(
      (s) => s.type === 'social_tap_comment_target'
    );
    const filterIdx = body.findIndex(
      (s) => s.type === 'social_apply_comment_filter'
    );
    const commentIdx = body.findIndex(
      (s) => s.type === 'extract' && s.entity === 'comments'
    );
    assert.ok(
      postIdx >= 0 &&
        findIdx >= 0 &&
        tapIdx >= 0 &&
        filterIdx >= 0 &&
        commentIdx >= 0
    );
    assert.ok(
      postIdx < findIdx &&
        findIdx < tapIdx &&
        tapIdx < filterIdx &&
        filterIdx < commentIdx
    );
    const between = body.slice(postIdx + 1, commentIdx);
    assert.ok(
      !between.some((s) => s.type === 'key' && s.key === 'back'),
      'back step before comment extract breaks detail flow'
    );
  }
});
