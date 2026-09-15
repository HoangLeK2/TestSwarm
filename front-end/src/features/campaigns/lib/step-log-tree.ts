import type { StepLogEntry } from '../types';

/**
 * `foldEventsToStepLog` returns one row per *run* of a step, sorted by
 * `depth:index:step_id:occurrence` — grouped by step, not by loop iteration.
 * This regroups those rows by the iteration they actually ran in, using the
 * `step_path` the workflow stamped on every event.
 */
export type StepLogNode =
  | { kind: 'step'; entry: StepLogEntry }
  | {
      kind: 'iteration';
      key: string;
      loopId: string;
      iter: number;
      children: StepLogNode[];
    };

/** `stepId[#loopIter][.branch]` — mirrors `_step_segment` in trace_context.py. */
const SEGMENT = /^([^#.]+)(?:#(\d+))?(?:\.(.+))?$/;

type Bucket = {
  steps: StepLogEntry[];
  iters: Map<string, { loopId: string; iter: number; bucket: Bucket }>;
};

function emptyBucket(): Bucket {
  return { steps: [], iters: new Map() };
}

function place(root: Bucket, entry: StepLogEntry): void {
  let current = root;
  let prefix = '';
  for (const segment of (entry.step_path ?? '').split('/')) {
    if (!segment) continue;
    prefix = prefix ? `${prefix}/${segment}` : segment;
    const match = SEGMENT.exec(segment);
    if (!match?.[2]) continue;
    let group = current.iters.get(prefix);
    if (!group) {
      group = { loopId: match[1], iter: Number(match[2]), bucket: emptyBucket() };
      current.iters.set(prefix, group);
    }
    current = group.bucket;
  }
  current.steps.push(entry);
}

function toNodes(bucket: Bucket): StepLogNode[] {
  // Anchor each loop's iterations right after the loop step itself.
  const anchor = new Map<string, number>();
  for (const entry of bucket.steps) {
    if (entry.step_id && !anchor.has(entry.step_id)) {
      anchor.set(entry.step_id, entry.index);
    }
  }
  const rows: { order: number; iter: number; node: StepLogNode }[] = [
    ...bucket.steps.map((entry) => ({
      order: entry.index,
      iter: -1,
      node: { kind: 'step', entry } as StepLogNode
    })),
    ...[...bucket.iters.entries()].map(([key, group]) => ({
      order: anchor.get(group.loopId) ?? Number.MAX_SAFE_INTEGER,
      iter: group.iter,
      node: {
        kind: 'iteration',
        key,
        loopId: group.loopId,
        iter: group.iter,
        children: toNodes(group.bucket)
      } as StepLogNode
    }))
  ];
  rows.sort((a, b) => a.order - b.order || a.iter - b.iter);
  return rows.map((row) => row.node);
}

export function buildStepLogTree(entries: StepLogEntry[]): StepLogNode[] {
  const root = emptyBucket();
  for (const entry of entries) place(root, entry);
  return toNodes(root);
}

export function stepLogNodeStats(nodes: StepLogNode[]): {
  steps: number;
  failed: number;
} {
  let steps = 0;
  let failed = 0;
  for (const node of nodes) {
    if (node.kind === 'step') {
      steps += 1;
      if (node.entry.status === 'failed' || node.entry.ok === false) failed += 1;
      continue;
    }
    const child = stepLogNodeStats(node.children);
    steps += child.steps;
    failed += child.failed;
  }
  return { steps, failed };
}
