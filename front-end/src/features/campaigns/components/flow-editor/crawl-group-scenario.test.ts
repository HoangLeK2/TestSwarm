import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import type { FlowStep } from '../scenario-steps/types';
import {
  applyChildStepEdit,
  getChildStep,
  updateChildInStep
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './bracket-step-tree.ts';
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

const FB_GROUP_STEPS = loadJsonSteps('device_farm/scenarios/fb_group_crawl.json');
const CRAWL_GROUP_STEPS = loadJsonSteps('agent-boot/Crawl group (2).json');

const REQUIRED_CRAWL_TYPES = [
  'loop',
  'extract',
  'fb_tap_comment_button',
  'if_element',
  'scroll_down',
  'key',
  'tap_selector',
  'input_text'
] as const;

test('crawl fixtures have well-formed step types', () => {
  assertAllStepsHaveType(FB_GROUP_STEPS, 'fb_group_crawl');
  assertAllStepsHaveType(CRAWL_GROUP_STEPS, 'crawl group (2)');
});

test('crawl fixtures contain comment crawl node chain', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const types = countStepTypes(steps);
    assert.ok(types.get('fb_tap_comment_button')! >= 1, 'missing fb_tap_comment_button');
    const commentExtracts = walkFlowStepsWithPaths(steps).filter(
      (v) => v.step.type === 'extract' && v.step.strategy === 'fb_comments'
    );
    assert.ok(commentExtracts.length >= 1, 'missing extract fb_comments');
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
      assert.ok(resolved, `unresolved path depth=${visit.depth} type=${visit.step.type}`);
      assert.equal(resolved.type, visit.step.type);
    }
  }
});

test('fb_comments extract fields round-trip through updateStepAtPath', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const extracts = walkFlowStepsWithPaths(steps).filter(
      (v) => v.step.type === 'extract' && v.step.strategy === 'fb_comments'
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

test('fb_tap_comment_button then-branch edits via bracket-step-tree helpers', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const taps = walkFlowStepsWithPaths(steps).filter(
      (v) => v.step.type === 'fb_tap_comment_button'
    );
    assert.ok(taps.length >= 1);
    for (const { step } of taps) {
      const thenSteps = (step as FlowStep & { then?: FlowStep[] }).then ?? [];
      const extractIdx = thenSteps.findIndex(
        (s) => s.type === 'extract' && s.strategy === 'fb_comments'
      );
      assert.ok(extractIdx >= 0, 'fb_tap_comment_button then branch missing fb_comments extract');
      const extract = getChildStep(step, 'then', extractIdx)!;
      assert.equal(extract.type, 'extract');
      assert.equal(extract.strategy, 'fb_comments');
      const edited = { ...extract, max_items: 55 } as FlowStep;
      const nextTap = updateChildInStep(step, 'then', extractIdx, edited);
      assert.equal(getChildStep(nextTap, 'then', extractIdx)?.max_items, 55);
      const viaApply = applyChildStepEdit(nextTap, { listKey: 'then', ci: extractIdx }, {
        ...edited,
        max_items: 66
      } as FlowStep);
      assert.equal(getChildStep(viaApply!, 'then', extractIdx)?.max_items, 66);
    }
  }
});

test('patchStepByFlowgramId updates nested extract when _fgId is present', () => {
  const loop = CRAWL_GROUP_STEPS.find((s) => s.type === 'loop');
  assert.ok(loop);
  const tap = ((loop as FlowStep & { steps?: FlowStep[] }).steps ?? []).find(
    (s) => s.type === 'fb_tap_comment_button'
  );
  assert.ok(tap);
  const thenSteps = (tap as FlowStep & { then?: FlowStep[] }).then ?? [];
  const extractIdx = thenSteps.findIndex(
    (s) => s.type === 'extract' && s.strategy === 'fb_comments'
  );
  assert.ok(extractIdx >= 0);
  const extract = thenSteps[extractIdx]!;
  const fgId = 'perf-extract-fg';
  const tapWithFg = {
    ...tap,
    _fgId: 'tap-fg',
    then: thenSteps.map((s, i) =>
      i === extractIdx ? { ...s, _fgId: fgId } : s
    )
  } as FlowStep;
  const stepsWithFg = CRAWL_GROUP_STEPS.map((s) =>
    s.type === 'loop'
      ? ({
          ...s,
          steps: ((s as FlowStep & { steps?: FlowStep[] }).steps ?? []).map((c) =>
            c.type === 'fb_tap_comment_button' ? tapWithFg : c
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
      (v) => v.step.type === 'extract' && v.step.strategy === 'fb_comments'
    );
    for (const { step } of extracts) {
      assert.equal(step.dedupe_field, 'comment_key');
      if (step.require_verified_parent != null) {
        assert.equal(step.require_verified_parent, true);
      }
    }
  }
});

test('post extract stays before fb_tap_comment_button inside loop (no back between)', () => {
  for (const steps of [FB_GROUP_STEPS, CRAWL_GROUP_STEPS]) {
    const loop = steps.find((s) => s.type === 'loop') as FlowStep & {
      steps?: FlowStep[];
    };
    assert.ok(loop?.steps?.length);
    const body = loop.steps!;
    const postIdx = body.findIndex(
      (s) => s.type === 'extract' && s.strategy === 'fb_posts'
    );
    const tapIdx = body.findIndex((s) => s.type === 'fb_tap_comment_button');
    assert.ok(postIdx >= 0 && tapIdx >= 0);
    const between = body.slice(postIdx + 1, tapIdx);
    assert.ok(
      !between.some((s) => s.type === 'key' && s.key === 'back'),
      'back step between post extract and comment tap breaks detail flow'
    );
  }
});
