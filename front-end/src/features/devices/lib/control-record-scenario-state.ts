import { generateNKeysBetween } from 'fractional-indexing';
import { nanoid } from 'nanoid';
import type {
  FlowEdge,
  FlowNode,
  FlowStep
} from '@/features/campaigns/components/scenario-steps/types';
import { stepsToGraph } from '@/features/campaigns/utils/steps-to-graph';

export type ControlRecordStep = FlowStep & { _id: string };

export type ControlRecordScenarioSnapshot = {
  steps: ControlRecordStep[];
  nodes: FlowNode[];
  edges: FlowEdge[];
};

const CONDITION_TYPES = new Set([
  'if',
  'if_element',
  'if_variable',
  'social_open_comments',
  'social_open_comments'
]);
const LOOP_TYPES = new Set(['loop', 'repeat', 'repeat_until']);

function resolveSiblingOrders(steps: FlowStep[]): string[] {
  const existing = steps.map((step) =>
    typeof step.order === 'string' && step.order ? step.order : null
  );
  const alreadyOrdered = existing.every(
    (order, index) =>
      order !== null && (index === 0 || existing[index - 1]! < order)
  );

  return alreadyOrdered
    ? (existing as string[])
    : generateNKeysBetween(null, null, steps.length);
}

function normalizeStepList(
  steps: FlowStep[],
  usedIds: Set<string>
): ControlRecordStep[] {
  const orders = resolveSiblingOrders(steps);

  return steps.map((step, index) => {
    const current = step as FlowStep & { _id?: string };
    const requestedId =
      typeof current.id === 'string' && current.id.trim() ? current.id : null;
    const id =
      requestedId && !usedIds.has(requestedId) ? requestedId : nanoid(10);
    usedIds.add(id);
    const normalized: ControlRecordStep = {
      ...current,
      id,
      order: orders[index]!,
      _id:
        typeof current._id === 'string' && current._id.trim() ? current._id : id
    };

    if (CONDITION_TYPES.has(current.type)) {
      normalized.then = normalizeStepList(
        Array.isArray(current.then) ? current.then : [],
        usedIds
      );
      normalized.else = normalizeStepList(
        Array.isArray(current.else)
          ? current.else
          : Array.isArray(current.else_steps)
            ? current.else_steps
            : [],
        usedIds
      );
      delete normalized.else_steps;
    } else if (LOOP_TYPES.has(current.type)) {
      normalized.steps = normalizeStepList(
        Array.isArray(current.steps) ? current.steps : [],
        usedIds
      );
    } else if (current.type === 'random_pick') {
      normalized.branches = (
        Array.isArray(current.branches) ? current.branches : []
      ).map((branch: Record<string, unknown>) => ({
        ...branch,
        steps: normalizeStepList(
          Array.isArray(branch.steps) ? (branch.steps as FlowStep[]) : [],
          usedIds
        )
      }));
    }

    return normalized;
  });
}

export function buildControlRecordScenarioSnapshot(
  steps: FlowStep[]
): ControlRecordScenarioSnapshot {
  const normalizedSteps = normalizeStepList(steps, new Set());
  const graph = stepsToGraph(normalizedSteps as Record<string, unknown>[]);

  return {
    steps: normalizedSteps,
    nodes: graph.nodes,
    edges: graph.edges
  };
}
