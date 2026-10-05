import assert from 'node:assert/strict';
import test from 'node:test';

import {
  analyzeStepVariableLineage,
  type StepVariableLineage
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './step-variable-lineage.ts';
import type { FlowStep } from '../components/scenario-steps/types.ts';

const steps = (value: FlowStep[]) => value;

function byPath(result: ReturnType<typeof analyzeStepVariableLineage>) {
  return (pathKey: string): StepVariableLineage => {
    const entry = result.byPathKey.get(pathKey);
    assert.ok(entry, `missing lineage entry for ${pathKey}`);
    return entry;
  };
}

test('set_variable makes a later token reference available in sequence order', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'set_variable', name: 'GREETING', value: 'hello' },
        { type: 'input_text', text: '${GREETING}' }
      ])
    )
  );

  assert.deepEqual(get('steps:1').issues, []);
  assert.deepEqual(
    get('steps:1').references.map((ref) => ref.name),
    ['GREETING']
  );
});

test('a variable referenced before it is written is reported as a future reference', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'input_text', text: '${GREETING}' },
        { type: 'set_variable', name: 'GREETING', value: 'hello' }
      ])
    )
  );

  assert.equal(get('steps:0').issues[0]?.kind, 'future_reference');
  assert.equal(get('steps:0').issues[0]?.variable, 'GREETING');
});

test('unknown token references remain warning-only lineage issues', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([{ type: 'input_text', text: '${MISSING_NAME}' }])
    )
  );

  assert.equal(get('steps:0').issues[0]?.kind, 'unknown_reference');
  assert.equal(get('steps:0').issues[0]?.variable, 'MISSING_NAME');
});

test('branch-only production is possible but not guaranteed after the branch', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'if_variable',
          name: 'HAS_TARGET',
          equals: 'true',
          then: [{ type: 'set_variable', name: 'TARGET_NAME', value: 'A' }],
          else: []
        },
        { type: 'input_text', text: '${TARGET_NAME}' }
      ]),
      ['HAS_TARGET']
    )
  );

  assert.equal(get('steps:1').issues[0]?.kind, 'maybe_unavailable');
  assert.equal(get('steps:1').issues[0]?.variable, 'TARGET_NAME');
  assert.equal(get('steps:1').issues[0]?.producerPathKey, 'steps:0/then:0');
  assert.equal(get('steps:1').issues[0]?.producerStepType, 'set_variable');
});

test('production in every branch is guaranteed after the branch', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'if_variable',
          name: 'HAS_TARGET',
          equals: 'true',
          then: [{ type: 'set_variable', name: 'TARGET_NAME', value: 'A' }],
          else: [{ type: 'set_variable', name: 'TARGET_NAME', value: 'B' }]
        },
        { type: 'input_text', text: '${TARGET_NAME}' }
      ]),
      ['HAS_TARGET']
    )
  );

  assert.deepEqual(get('steps:1').issues, []);
});

test('loop variables are available inside the loop body but not after the loop', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'loop',
          list: ['a', 'b'],
          loop_var: 'ITEM',
          steps: [{ type: 'input_text', text: '${ITEM}' }]
        },
        { type: 'input_text', text: '${ITEM}' }
      ])
    )
  );

  assert.deepEqual(get('steps:0/steps:0').issues, []);
  assert.equal(get('steps:1').issues[0]?.kind, 'unknown_reference');
  assert.equal(get('steps:1').issues[0]?.variable, 'ITEM');
});

test('source_var can read a post scan save_as only after the scan step', () => {
  const valid = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'social_scan_posts_interact',
          save_as: '_post_scan'
        },
        {
          type: 'social_open_author_from_post_match',
          source_var: '_post_scan',
          save_as: '_people_target'
        }
      ])
    )
  );

  assert.deepEqual(valid('steps:1').issues, []);

  const invalid = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'social_open_author_from_post_match',
          source_var: '_post_scan',
          save_as: '_people_target'
        },
        {
          type: 'social_scan_posts_interact',
          save_as: '_post_scan'
        }
      ])
    )
  );

  assert.equal(invalid('steps:0').issues[0]?.kind, 'future_reference');
  assert.equal(invalid('steps:0').issues[0]?.source, 'source_var');
});

test('post-match opener uses the runtime default _post_scan source_var', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'social_scan_posts_interact', save_as: '_post_scan' },
        { type: 'social_open_author_from_post_match', save_as: '_target' }
      ])
    )
  );

  assert.deepEqual(get('steps:1').issues, []);
  assert.deepEqual(
    get('steps:1').references.map((ref) => [ref.name, ref.source]),
    [['_post_scan', 'source_var']]
  );
});

test('post-match opener warns when source_var was not produced by a post scan', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'set_variable', name: '_post_scan', value: [] },
        { type: 'social_open_author_from_post_match', save_as: '_target' }
      ])
    )
  );

  const issue = get('steps:1').issues[0];
  assert.equal(issue?.kind, 'source_var_without_scan');
  assert.equal(issue?.variable, '_post_scan');
  assert.equal(issue?.producerPathKey, 'steps:0');
  assert.equal(issue?.producerStepType, 'set_variable');
});

test('run_scenario variable overrides report missing parent variable references', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'run_scenario',
          scenario_name: 'child',
          variables: { TARGET_NAME: '${MISSING_TARGET_NAME}' }
        }
      ])
    )
  );

  assert.deepEqual(
    get('steps:0').references.map((ref) => [ref.name, ref.source]),
    [['MISSING_TARGET_NAME', 'run_scenario_variable']]
  );
  assert.equal(get('steps:0').issues[0]?.kind, 'unknown_reference');
});

test('connection_request warns when it has no verified target or candidate guard', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([{ type: 'connection_request', action: 'request' }])
    )
  );

  assert.equal(get('steps:0').issues[0]?.kind, 'missing_verified_target');
  assert.equal(get('steps:0').issues[0]?.source, 'require_verified_target');
});

test('connection_request accepts a verified profile target or candidate entity guard', () => {
  const verified = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'social_select_target',
          save_as: '_people_target',
          save_success_as: 'PEOPLE_PROFILE_SELECTED'
        },
        {
          type: 'connection_request',
          require_verified_target: '_people_target'
        }
      ])
    )
  );
  const candidate = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'connection_request',
          candidate_entity_id: '${TARGET_ENTITY_ID}'
        }
      ]),
      ['TARGET_ENTITY_ID']
    )
  );

  assert.deepEqual(verified('steps:1').issues, []);
  assert.deepEqual(candidate('steps:0').issues, []);
});

test('connection_request warns when verified target was produced by a raw variable step', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'set_variable', name: '_people_target', value: {} },
        {
          type: 'connection_request',
          require_verified_target: '_people_target'
        }
      ])
    )
  );

  const issue = get('steps:1').issues.find(
    (item) => item.kind === 'verified_target_without_profile'
  );
  assert.ok(issue);
  assert.equal(issue.variable, '_people_target');
  assert.equal(issue.producerPathKey, 'steps:0');
  assert.equal(issue.producerStepType, 'set_variable');
});

test('post-match profile opener declares its default runtime variables', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'social_scan_posts_interact', save_as: '_post_scan' },
        { type: 'social_open_commenter_from_post_match' }
      ])
    )
  );

  const produced = get('steps:1').produced.map((item) => item.name);
  assert.ok(produced.includes('_people_target'));
  assert.ok(produced.includes('PEOPLE_PROFILE_SELECTED'));
  assert.ok(produced.includes('COMMENTER_PROFILE_OPENED'));
  assert.ok(produced.includes('COMMENT_SHEET_OPENED'));
});

test('comment flow warns when required sequence steps are missing', () => {
  const get = byPath(
    analyzeStepVariableLineage(steps([{ type: 'social_apply_comment_filter' }]))
  );

  assert.equal(get('steps:0').issues[0]?.kind, 'comment_flow_missing_step');
  assert.equal(get('steps:0').issues[0]?.variable, 'social_tap_comment_target');
});

test('comment extract warns when comment filter did not run earlier', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'extract',
          platform: 'instagram',
          entity: 'comments',
          dedupe_field: 'comment_key'
        }
      ])
    )
  );

  assert.equal(get('steps:0').issues[0]?.kind, 'comment_flow_missing_step');
  assert.equal(
    get('steps:0').issues[0]?.variable,
    'social_apply_comment_filter'
  );
});

test('comment flow accepts the split comment sequence in order', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        { type: 'social_find_comment_button' },
        { type: 'social_tap_comment_target' },
        { type: 'social_apply_comment_filter' },
        {
          type: 'extract',
          platform: 'instagram',
          entity: 'comments',
          dedupe_field: 'comment_key'
        }
      ])
    )
  );

  assert.deepEqual(get('steps:1').issues, []);
  assert.deepEqual(get('steps:2').issues, []);
  assert.deepEqual(get('steps:3').issues, []);
});

test('comment flow warns when required step only exists on one branch', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'if_variable',
          name: 'HAS_COMMENT_BUTTON',
          then: [{ type: 'social_find_comment_button' }],
          else: []
        },
        { type: 'social_tap_comment_target' }
      ]),
      ['HAS_COMMENT_BUTTON']
    )
  );

  assert.equal(get('steps:1').issues[0]?.kind, 'comment_flow_missing_step');
  assert.equal(
    get('steps:1').issues[0]?.variable,
    'social_find_comment_button'
  );
});

test('candidate lease token without candidate_entity_id reports the runtime contract warning', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([
        {
          type: 'connection_request',
          require_verified_target: '_people_target',
          candidate_lease_token: '${CANDIDATE_LEASE_TOKEN}'
        }
      ]),
      ['_people_target', 'CANDIDATE_LEASE_TOKEN']
    )
  );

  assert.equal(
    get('steps:0').issues.at(-1)?.kind,
    'candidate_lease_without_entity'
  );
});

test('built-in account variables are not flagged as missing', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([{ type: 'input_text', text: '${__ACCOUNT_USERNAME__}' }])
    )
  );

  assert.deepEqual(get('steps:0').issues, []);
});

test('save_as declares an output and is not treated as a read reference', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([{ type: 'extract_text_ocr', save_as: 'OCR_TEXT' }])
    )
  );

  assert.deepEqual(get('steps:0').references, []);
  assert.deepEqual(
    get('steps:0').produced.map((item) => item.name),
    ['OCR_TEXT']
  );
});

test('source pool output_prefix expands produced variables but is not itself a variable', () => {
  const get = byPath(
    analyzeStepVariableLineage(
      steps([{ type: 'use_source_pool', output_prefix: 'PAGE' }])
    )
  );

  const produced = get('steps:0').produced.map((item) => item.name);
  assert.ok(produced.includes('PAGE_NAME'));
  assert.ok(produced.includes('PAGE_ENTITY_ID'));
  assert.equal(produced.includes('PAGE'), false);
});
