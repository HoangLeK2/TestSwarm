import type { FlowStep } from '../scenario-steps/types';

/**
 * Variables a step *writes* at runtime.
 *
 * The editor previously only knew about variables a step *reads* or explicitly
 * declares (`set_variable`, `if_variable`, `set_var`, `run_scenario`), so
 * anything produced through `save_as` — OCR text, resolved targets, leased
 * candidates — never appeared in the "available variables" picker. Authors had
 * to know the name and type it by hand.
 *
 * Kept in sync with the `sc.var_ctx.set(...)` calls in
 * `device_farm/tasks/scenario/steps/`.
 */

/** Steps whose `save_as` names the variable they fill. */
const SAVE_AS_PRODUCERS = new Set<string>([
  'extract',
  'extract_text_ocr',
  'extract_text_ai',
  'extract_text_hierarchy',
  'extract_screen_data',
  'social_select_target',
  'social_connect_visible_people',
  'social_scan_posts_interact',
  'social_open_author_from_post_match',
  'social_open_commenter_from_post_match',
  'content_interaction',
  'connection_request',
  'community_membership'
]);

/** Steps that always write the same fixed names. */
const FIXED_PRODUCERS: Record<string, string[]> = {
  platform_session_gate: ['PLATFORM_SESSION_READY'],
  lease_connection_candidate: [
    'CANDIDATE_AVAILABLE',
    'CANDIDATE_ID',
    'CANDIDATE_ENTITY_ID',
    'CANDIDATE_EXTERNAL_ID',
    'CANDIDATE_NAME',
    'CANDIDATE_URL',
    'CANDIDATE_LEASE_TOKEN',
    'TARGET_ENTITY_ID',
    'TARGET_EXTERNAL_ID',
    'TARGET_NAME',
    'TARGET_URL'
  ]
};

/** Suffixes appended to `output_prefix` by the source-pool steps. */
const PREFIXED_SUFFIXES = [
  'ENTITY_ID',
  'PLATFORM',
  'ENTITY_TYPE',
  'EXTERNAL_ID',
  'URL',
  'NAME'
];

function pushName(out: Set<string>, raw: unknown) {
  const name = String(raw ?? '').trim();
  // A `${VAR}`-shaped value is a reference, not a new variable name.
  if (name && !name.startsWith('$')) out.add(name);
}

/** Variable names this single step writes. Does not recurse into children. */
export function variablesProducedByStep(step: FlowStep): string[] {
  const out = new Set<string>();
  const type = String(step.type ?? '');

  if (SAVE_AS_PRODUCERS.has(type)) {
    pushName(out, step.save_as);
    pushName(out, step.data_var);
    pushName(out, step.extract_var);
  }
  if (type === 'social_select_target') {
    pushName(out, step.save_success_as);
  }
  for (const name of FIXED_PRODUCERS[type] ?? []) out.add(name);

  if (type === 'use_source_pool' || type === 'lease_source_target') {
    const prefix = String(step.output_prefix ?? 'GROUP').trim();
    if (prefix && !prefix.startsWith('$')) {
      for (const suffix of PREFIXED_SUFFIXES) out.add(`${prefix}_${suffix}`);
    }
  }
  if (type === 'loop') {
    pushName(out, step.loop_var);
  }

  return Array.from(out);
}

/** The primary variable a step fills — what a "use this result" action targets. */
export function primaryProducedVariable(step: FlowStep): string | null {
  const type = String(step.type ?? '');
  if (!SAVE_AS_PRODUCERS.has(type)) return null;
  const name = String(step.save_as ?? step.data_var ?? '').trim();
  return name && !name.startsWith('$') ? name : null;
}
