import { collectScenarioVariableReferences } from '@/lib/scenario-variable-references';
import type { FlowStep } from '../components/scenario-steps/types';
import { variablesProducedByStep } from '../components/flow-editor/step-produced-variables';
import {
  stepTreePathKey,
  type StepTreePathSegment
} from './step-tree-intelligence';

export type StepVariableReferenceSource =
  | 'token'
  | 'if_variable'
  | 'run_scenario_variable'
  | 'runtime_step'
  | 'source_var'
  | 'require_verified_target'
  | 'target_count_var'
  | 'candidate_entity_id'
  | 'candidate_lease_token';

export type StepVariableProductionSource =
  | 'step_output'
  | 'set_variable'
  | 'set_var'
  | 'loop_var';

export type StepVariableLineageIssueKind =
  | 'unknown_reference'
  | 'future_reference'
  | 'maybe_unavailable'
  | 'missing_verified_target'
  | 'candidate_lease_without_entity'
  | 'source_var_without_scan'
  | 'verified_target_without_profile'
  | 'comment_flow_missing_step';

export type StepVariableReference = {
  name: string;
  source: StepVariableReferenceSource;
};

export type StepVariableProduction = {
  name: string;
  source: StepVariableProductionSource;
  stepType: string;
};

export type StepVariableProducerContext = {
  name: string;
  source: StepVariableProductionSource;
  stepType: string;
  pathKey: string;
};

export type StepVariableLineageIssue = {
  kind: StepVariableLineageIssueKind;
  variable: string;
  source: StepVariableReferenceSource;
  pathKey: string;
  producerPathKey?: string;
  producerStepType?: string;
};

export type StepVariableLineage = {
  step: FlowStep;
  path: StepTreePathSegment[];
  pathKey: string;
  depth: number;
  references: StepVariableReference[];
  produced: StepVariableProduction[];
  availableBefore: string[];
  guaranteedAfter: string[];
  possibleAfter: string[];
  issues: StepVariableLineageIssue[];
};

export type StepVariableLineageResult = {
  entries: StepVariableLineage[];
  byPathKey: Map<string, StepVariableLineage>;
  allProduced: string[];
  allReferenced: string[];
  issues: StepVariableLineageIssue[];
};

type VariableState = {
  guaranteed: Set<string>;
  possible: Set<string>;
  producers: Map<string, StepVariableProducerContext[]>;
  guaranteedStepTypes: Set<string>;
  possibleStepTypes: Set<string>;
};

type ChildContainer = {
  listKey: string;
  steps: FlowStep[];
};

const DIRECT_REFERENCE_FIELDS = [
  'source_var',
  'require_verified_target',
  'target_count_var',
  'candidate_entity_id',
  'candidate_lease_token'
] as const;

const OUTPUT_NAME_FIELDS = [
  'save_as',
  'save_success_as',
  'save_opened_as',
  'save_sheet_opened_as',
  'data_var',
  'extract_var'
] as const;

const OUTPUT_NAME_FIELD_SET = new Set<string>(OUTPUT_NAME_FIELDS);
const TOKEN_SKIP_FIELDS = new Set<string>([
  ...OUTPUT_NAME_FIELDS,
  'output_prefix'
]);

const CHILD_LIST_FIELDS = new Set(['steps', 'then', 'else', 'branches']);
const RUN_SCENARIO_VARIABLES_KEY = 'variables';
const VERIFIED_TARGET_PRODUCERS = new Set([
  'social_select_target',
  'social_open_author_from_post_match',
  'social_open_commenter_from_post_match'
]);

const TOKEN_ONLY_RE = /^\$\{(\w+)\}$/;

export function analyzeStepVariableLineage(
  steps: FlowStep[],
  initialVariables: string[] = []
): StepVariableLineageResult {
  const entries: StepVariableLineage[] = [];
  const initial = normalizeNameSet(initialVariables);
  const state: VariableState = {
    guaranteed: initial,
    possible: new Set(initial),
    producers: new Map(),
    guaranteedStepTypes: new Set(),
    possibleStepTypes: new Set()
  };

  walkList(steps, [], 'steps', 0, state, new Set(), entries);

  const allProduced = new Set<string>();
  const allReferenced = new Set<string>();
  const issues: StepVariableLineageIssue[] = [];
  const byPathKey = new Map<string, StepVariableLineage>();

  for (const entry of entries) {
    byPathKey.set(entry.pathKey, entry);
    entry.produced.forEach((production) => allProduced.add(production.name));
    entry.references.forEach((reference) => allReferenced.add(reference.name));
    issues.push(...entry.issues);
  }

  return {
    entries,
    byPathKey,
    allProduced: sortedNames(allProduced),
    allReferenced: sortedNames(allReferenced),
    issues
  };
}

function walkList(
  steps: FlowStep[],
  parentPath: StepTreePathSegment[],
  containerKey: string,
  depth: number,
  state: VariableState,
  futureAfterList: Set<string>,
  entries: StepVariableLineage[]
): VariableState {
  let current = cloneState(state);

  steps.forEach((step, ci) => {
    const path = [...parentPath, { listKey: containerKey, ci }];
    const pathKey = stepTreePathKey(path);
    const references = referencesForStep(step);
    const produced = productionsForStep(step);
    const futureProduced = unionSets(
      collectProducedFromSteps(steps.slice(ci + 1)),
      futureAfterList
    );
    const entry: StepVariableLineage = {
      step,
      path,
      pathKey,
      depth,
      references,
      produced,
      availableBefore: sortedNames(current.possible),
      guaranteedAfter: sortedNames(current.guaranteed),
      possibleAfter: sortedNames(current.possible),
      issues: references.flatMap((reference) =>
        issueForReference(reference, current, futureProduced, pathKey)
      )
    };
    entry.issues.push(...contractIssuesForStep(step, current, pathKey));
    entries.push(entry);

    current = applyStep(step, path, depth, current, futureProduced, entries);
    entry.guaranteedAfter = sortedNames(current.guaranteed);
    entry.possibleAfter = sortedNames(current.possible);
  });

  return current;
}

function applyStep(
  step: FlowStep,
  path: StepTreePathSegment[],
  depth: number,
  state: VariableState,
  futureAfterStep: Set<string>,
  entries: StepVariableLineage[]
): VariableState {
  const type = String(step.type ?? '');
  const childContainers = childrenForStep(step);

  if (type === 'loop' || type === 'repeat' || type === 'repeat_until') {
    const body = childContainers[0];
    const pathKey = stepTreePathKey(path);
    if (!body) {
      return markStepType(
        addProductions(state, productionsForStep(step), pathKey),
        type
      );
    }

    const bodyState = cloneState(state);
    if (type === 'loop') {
      for (const production of productionsForStep(step)) {
        if (production.source === 'loop_var') {
          bodyState.guaranteed.add(production.name);
          bodyState.possible.add(production.name);
          addProducer(bodyState.producers, {
            name: production.name,
            source: production.source,
            stepType: production.stepType,
            pathKey
          });
        }
      }
    }

    const bodyResult = walkList(
      body.steps,
      path,
      body.listKey,
      depth + 1,
      bodyState,
      futureAfterStep,
      entries
    );
    return mergeLoopState(state, bodyState, bodyResult);
  }

  if (isBranchingType(type)) {
    const branchResults = childContainers.map((child) =>
      walkList(
        child.steps,
        path,
        child.listKey,
        depth + 1,
        cloneState(state),
        futureAfterStep,
        entries
      )
    );
    return mergeBranchStates(state, branchResults);
  }

  return markStepType(
    addProductions(state, productionsForStep(step), stepTreePathKey(path)),
    type
  );
}

function issueForReference(
  reference: StepVariableReference,
  state: VariableState,
  futureProduced: Set<string>,
  pathKey: string
): StepVariableLineageIssue[] {
  if (
    isBuiltInVariable(reference.name) ||
    state.guaranteed.has(reference.name)
  ) {
    return [];
  }
  if (state.possible.has(reference.name)) {
    const producer = firstProducer(state, reference.name);
    return [
      {
        kind: 'maybe_unavailable',
        variable: reference.name,
        source: reference.source,
        pathKey,
        producerPathKey: producer?.pathKey,
        producerStepType: producer?.stepType
      }
    ];
  }
  return [
    {
      kind: futureProduced.has(reference.name)
        ? 'future_reference'
        : 'unknown_reference',
      variable: reference.name,
      source: reference.source,
      pathKey
    }
  ];
}

function productionsForStep(step: FlowStep): StepVariableProduction[] {
  const out = new Map<string, StepVariableProduction>();
  const type = String(step.type ?? '');

  const add = (raw: unknown, source: StepVariableProductionSource) => {
    const name = normalizeProducedName(raw);
    if (!name) return;
    out.set(`${name}:${source}`, { name, source, stepType: type });
  };

  if (type === 'set_variable') add(step.name, 'set_variable');
  if (type === 'set_var') add(step.key, 'set_var');
  if (type === 'loop') add(step.loop_var, 'loop_var');
  if (type === 'social_select_target') {
    add(step.save_as ?? '_people_target', 'step_output');
    add(step.save_success_as ?? 'PEOPLE_PROFILE_SELECTED', 'step_output');
  }
  if (
    type === 'social_open_author_from_post_match' ||
    type === 'social_open_commenter_from_post_match'
  ) {
    add(step.save_as ?? '_people_target', 'step_output');
    add(step.save_success_as ?? 'PEOPLE_PROFILE_SELECTED', 'step_output');
    add(
      step.save_opened_as ??
        (type === 'social_open_commenter_from_post_match'
          ? 'COMMENTER_PROFILE_OPENED'
          : 'AUTHOR_PROFILE_OPENED'),
      'step_output'
    );
    if (type === 'social_open_commenter_from_post_match') {
      add(step.save_sheet_opened_as ?? 'COMMENT_SHEET_OPENED', 'step_output');
    }
  }

  variablesProducedByStep(step).forEach((name) => {
    if (type === 'loop' && name === normalizeProducedName(step.loop_var)) {
      add(name, 'loop_var');
      return;
    }
    add(name, 'step_output');
  });

  for (const field of OUTPUT_NAME_FIELDS) add(step[field], 'step_output');

  return Array.from(out.values()).sort((a, b) =>
    a.name === b.name
      ? a.source.localeCompare(b.source)
      : a.name.localeCompare(b.name)
  );
}

function referencesForStep(step: FlowStep): StepVariableReference[] {
  const out = new Map<string, StepVariableReference>();
  const add = (raw: unknown, source: StepVariableReferenceSource) => {
    const name = normalizeReferenceName(raw);
    if (!name) return;
    out.set(`${name}:${source}`, { name, source });
  };

  collectTokenReferences(step).forEach((name) => add(name, 'token'));
  collectRunScenarioVariableReferences(step).forEach((name) =>
    add(name, 'run_scenario_variable')
  );

  const type = String(step.type ?? '');
  if (type === 'if_variable') {
    add(step.name, 'if_variable');
  }
  if (
    type === 'social_open_author_from_post_match' ||
    type === 'social_open_commenter_from_post_match'
  ) {
    add(step.source_var ?? '_post_scan', 'source_var');
  }
  for (const field of DIRECT_REFERENCE_FIELDS) {
    const raw = step[field];
    if (typeof raw !== 'string') continue;
    const token = TOKEN_ONLY_RE.exec(raw.trim());
    add(token?.[1] ?? raw, field);
  }

  return Array.from(out.values()).sort((a, b) =>
    a.name === b.name
      ? a.source.localeCompare(b.source)
      : a.name.localeCompare(b.name)
  );
}

function collectTokenReferences(step: FlowStep): string[] {
  const references = new Set<string>();

  const walk = (value: unknown, key?: string) => {
    if (key && (TOKEN_SKIP_FIELDS.has(key) || CHILD_LIST_FIELDS.has(key))) {
      return;
    }
    if (
      String(step.type ?? '') === 'run_scenario' &&
      key === RUN_SCENARIO_VARIABLES_KEY
    ) {
      return;
    }
    if (typeof value === 'string') {
      collectScenarioVariableReferences(value).forEach((name) =>
        references.add(name)
      );
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((child) => walk(child));
      return;
    }
    if (value && typeof value === 'object') {
      Object.entries(value as Record<string, unknown>).forEach(
        ([childKey, child]) => walk(child, childKey)
      );
    }
  };

  walk(step);
  return sortedNames(references);
}

function collectRunScenarioVariableReferences(step: FlowStep): string[] {
  if (String(step.type ?? '') !== 'run_scenario' || !step.variables) return [];
  return collectScenarioVariableReferences(step.variables);
}

function contractIssuesForStep(
  step: FlowStep,
  state: VariableState,
  pathKey: string
): StepVariableLineageIssue[] {
  const type = String(step.type ?? '');
  const issues: StepVariableLineageIssue[] = [];

  if (
    type === 'social_open_author_from_post_match' ||
    type === 'social_open_commenter_from_post_match'
  ) {
    const sourceVar = normalizeReferenceName(step.source_var ?? '_post_scan');
    if (
      sourceVar &&
      state.possible.has(sourceVar) &&
      hasKnownProducer(state, sourceVar) &&
      !hasProducerStepType(state, sourceVar, ['social_scan_posts_interact'])
    ) {
      const producer = firstProducer(state, sourceVar);
      issues.push({
        kind: 'source_var_without_scan',
        variable: sourceVar,
        source: 'source_var',
        pathKey,
        producerPathKey: producer?.pathKey,
        producerStepType: producer?.stepType
      });
    }
  }

  const requiredStep = requiredCommentFlowStep(type, step);
  if (requiredStep && !state.guaranteedStepTypes.has(requiredStep)) {
    issues.push({
      kind: 'comment_flow_missing_step',
      variable: requiredStep,
      source: 'runtime_step',
      pathKey
    });
  }

  if (type !== 'connection_request') return issues;

  const requireVerifiedTarget = String(
    step.require_verified_target ?? ''
  ).trim();
  const candidateEntityId = String(step.candidate_entity_id ?? '').trim();
  const candidateLeaseToken = String(step.candidate_lease_token ?? '').trim();

  if (!requireVerifiedTarget && !candidateEntityId) {
    issues.push({
      kind: 'missing_verified_target',
      variable: '_people_target',
      source: 'require_verified_target',
      pathKey
    });
  }
  if (requireVerifiedTarget) {
    const targetVar = normalizeReferenceName(requireVerifiedTarget);
    if (
      targetVar &&
      state.possible.has(targetVar) &&
      hasKnownProducer(state, targetVar) &&
      !hasProducerStepType(
        state,
        targetVar,
        Array.from(VERIFIED_TARGET_PRODUCERS)
      )
    ) {
      const producer = firstProducer(state, targetVar);
      issues.push({
        kind: 'verified_target_without_profile',
        variable: targetVar,
        source: 'require_verified_target',
        pathKey,
        producerPathKey: producer?.pathKey,
        producerStepType: producer?.stepType
      });
    }
  }
  if (candidateLeaseToken && !candidateEntityId) {
    issues.push({
      kind: 'candidate_lease_without_entity',
      variable: 'candidate_entity_id',
      source: 'candidate_entity_id',
      pathKey
    });
  }

  return issues;
}

function requiredCommentFlowStep(type: string, step: FlowStep): string | null {
  if (type === 'social_tap_comment_target') {
    return 'social_find_comment_button';
  }
  if (type === 'social_apply_comment_filter') {
    return 'social_tap_comment_target';
  }
  if (type === 'extract' && String(step.entity ?? '') === 'comments') {
    return 'social_apply_comment_filter';
  }
  return null;
}

function childrenForStep(step: FlowStep): ChildContainer[] {
  const type = String(step.type ?? '');
  if (type === 'loop' || type === 'repeat' || type === 'repeat_until') {
    return [
      { listKey: 'steps', steps: Array.isArray(step.steps) ? step.steps : [] }
    ];
  }
  if (
    type === 'if' ||
    type === 'if_element' ||
    type === 'if_variable' ||
    type === 'social_open_comments'
  ) {
    return [
      { listKey: 'then', steps: Array.isArray(step.then) ? step.then : [] },
      { listKey: 'else', steps: Array.isArray(step.else) ? step.else : [] }
    ];
  }
  if (type === 'random_pick') {
    return Array.isArray(step.branches)
      ? step.branches.map((branch: { steps?: unknown }, index: number) => ({
          listKey: `branches.${index}`,
          steps: Array.isArray(branch.steps) ? branch.steps : []
        }))
      : [];
  }
  return [];
}

function isBranchingType(type: string): boolean {
  return (
    type === 'if' ||
    type === 'if_element' ||
    type === 'if_variable' ||
    type === 'social_open_comments' ||
    type === 'random_pick'
  );
}

function mergeLoopState(
  outer: VariableState,
  bodyInitial: VariableState,
  bodyResult: VariableState
): VariableState {
  const next = cloneState(outer);
  difference(bodyResult.guaranteed, bodyInitial.guaranteed).forEach((name) => {
    next.possible.add(name);
    addProducersFrom(next.producers, bodyResult.producers, name);
  });
  difference(bodyResult.possible, bodyInitial.possible).forEach((name) => {
    next.possible.add(name);
    addProducersFrom(next.producers, bodyResult.producers, name);
  });
  difference(
    bodyResult.guaranteedStepTypes,
    bodyInitial.guaranteedStepTypes
  ).forEach((type) => next.possibleStepTypes.add(type));
  difference(
    bodyResult.possibleStepTypes,
    bodyInitial.possibleStepTypes
  ).forEach((type) => next.possibleStepTypes.add(type));
  return next;
}

function mergeBranchStates(
  outer: VariableState,
  branchResults: VariableState[]
): VariableState {
  if (branchResults.length === 0) return cloneState(outer);

  const next = cloneState(outer);
  const branchGuaranteed = branchResults.map((state) => state.guaranteed);
  const guaranteedAcrossBranches = intersectAll(branchGuaranteed);
  const branchGuaranteedStepTypes = branchResults.map(
    (state) => state.guaranteedStepTypes
  );
  const guaranteedStepTypesAcrossBranches = intersectAll(
    branchGuaranteedStepTypes
  );
  difference(guaranteedAcrossBranches, outer.guaranteed).forEach((name) => {
    next.guaranteed.add(name);
    next.possible.add(name);
    branchResults.forEach((branch) =>
      addProducersFrom(next.producers, branch.producers, name)
    );
  });
  difference(
    guaranteedStepTypesAcrossBranches,
    outer.guaranteedStepTypes
  ).forEach((type) => {
    next.guaranteedStepTypes.add(type);
    next.possibleStepTypes.add(type);
  });

  for (const branch of branchResults) {
    difference(branch.guaranteed, outer.guaranteed).forEach((name) => {
      next.possible.add(name);
      addProducersFrom(next.producers, branch.producers, name);
    });
    difference(branch.possible, outer.possible).forEach((name) => {
      next.possible.add(name);
      addProducersFrom(next.producers, branch.producers, name);
    });
    difference(branch.guaranteedStepTypes, outer.guaranteedStepTypes).forEach(
      (type) => next.possibleStepTypes.add(type)
    );
    difference(branch.possibleStepTypes, outer.possibleStepTypes).forEach(
      (type) => next.possibleStepTypes.add(type)
    );
  }

  return next;
}

function addProductions(
  state: VariableState,
  productions: StepVariableProduction[],
  pathKey: string
): VariableState {
  const next = cloneState(state);
  for (const production of productions) {
    if (production.source === 'loop_var') continue;
    next.guaranteed.add(production.name);
    next.possible.add(production.name);
    addProducer(next.producers, {
      name: production.name,
      source: production.source,
      stepType: production.stepType,
      pathKey
    });
  }
  return next;
}

function markStepType(state: VariableState, type: string): VariableState {
  if (!type) return state;
  const next = cloneState(state);
  next.guaranteedStepTypes.add(type);
  next.possibleStepTypes.add(type);
  return next;
}

function collectProducedFromSteps(steps: FlowStep[]): Set<string> {
  const out = new Set<string>();
  const walk = (step: FlowStep) => {
    productionsForStep(step).forEach((production) => out.add(production.name));
    childrenForStep(step).forEach((child) => child.steps.forEach(walk));
  };
  steps.forEach(walk);
  return out;
}

function cloneState(state: VariableState): VariableState {
  return {
    guaranteed: new Set(state.guaranteed),
    possible: new Set(state.possible),
    producers: cloneProducerMap(state.producers),
    guaranteedStepTypes: new Set(state.guaranteedStepTypes),
    possibleStepTypes: new Set(state.possibleStepTypes)
  };
}

function cloneProducerMap(
  producers: Map<string, StepVariableProducerContext[]>
): Map<string, StepVariableProducerContext[]> {
  const next = new Map<string, StepVariableProducerContext[]>();
  producers.forEach((items, name) => next.set(name, [...items]));
  return next;
}

function addProducer(
  producers: Map<string, StepVariableProducerContext[]>,
  producer: StepVariableProducerContext
) {
  const items = producers.get(producer.name) ?? [];
  if (
    items.some(
      (item) =>
        item.pathKey === producer.pathKey &&
        item.stepType === producer.stepType &&
        item.source === producer.source
    )
  ) {
    return;
  }
  producers.set(producer.name, [...items, producer]);
}

function addProducersFrom(
  target: Map<string, StepVariableProducerContext[]>,
  source: Map<string, StepVariableProducerContext[]>,
  name: string
) {
  for (const producer of source.get(name) ?? []) {
    addProducer(target, producer);
  }
}

function firstProducer(
  state: VariableState,
  name: string
): StepVariableProducerContext | undefined {
  return state.producers.get(name)?.[0];
}

function hasKnownProducer(state: VariableState, name: string): boolean {
  return (state.producers.get(name)?.length ?? 0) > 0;
}

function hasProducerStepType(
  state: VariableState,
  name: string,
  stepTypes: string[]
): boolean {
  const allowed = new Set(stepTypes);
  return (state.producers.get(name) ?? []).some((producer) =>
    allowed.has(producer.stepType)
  );
}

function normalizeNameSet(values: string[]): Set<string> {
  const out = new Set<string>();
  values.forEach((value) => {
    const name = normalizeReferenceName(value);
    if (name) {
      out.add(name);
    }
  });
  return out;
}

function normalizeProducedName(raw: unknown): string | null {
  const value = String(raw ?? '').trim();
  if (!value || value.startsWith('$')) return null;
  return value;
}

function normalizeReferenceName(raw: unknown): string | null {
  const value = String(raw ?? '').trim();
  if (!value) return null;
  const token = TOKEN_ONLY_RE.exec(value);
  return token?.[1] ?? value;
}

function isBuiltInVariable(name: string): boolean {
  return /^__.+__$/.test(name) || name.startsWith('__ACCOUNT_');
}

function sortedNames(values: Iterable<string>): string[] {
  return Array.from(values).sort((a, b) => a.localeCompare(b));
}

function unionSets(a: Set<string>, b: Set<string>): Set<string> {
  const out = new Set(a);
  b.forEach((value) => out.add(value));
  return out;
}

function difference(a: Set<string>, b: Set<string>): Set<string> {
  const out = new Set<string>();
  a.forEach((value) => {
    if (!b.has(value)) out.add(value);
  });
  return out;
}

function intersectAll(sets: Set<string>[]): Set<string> {
  if (sets.length === 0) return new Set();
  return new Set(
    Array.from(sets[0] ?? []).filter((value) =>
      sets.every((set) => set.has(value))
    )
  );
}
