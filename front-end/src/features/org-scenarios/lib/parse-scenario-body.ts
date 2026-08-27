import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { flowDocToSteps } from '@/features/scenario-templates/components/scenario-flow-editor/converters';
import type { FlowDocumentJSON } from '@flowgram.ai/fixed-layout-editor';

const NESTED_STEP_KEYS = ['then', 'else', 'steps'] as const;

function isNonEmptyConfig(config: unknown): config is Record<string, unknown> {
  return (
    typeof config === 'object' &&
    config !== null &&
    !Array.isArray(config) &&
    Object.keys(config).length > 0
  );
}

function normalizeNestedStepArray(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  return value
    .filter((s): s is Record<string, unknown> => !!s && typeof s === 'object')
    .map(normalizeSequenceStep);
}

function normalizeSequenceStep(raw: Record<string, unknown>): FlowStep {
  const config = raw.config;
  let step: Record<string, unknown>;

  if (raw.type && isNonEmptyConfig(config)) {
    step = {
      ...(config as Record<string, unknown>),
      type: String(raw.type),
      ...(raw.id != null ? { id: raw.id } : {})
    };
    for (const key of NESTED_STEP_KEYS) {
      if (key in raw && !(key in step)) {
        step[key] = normalizeNestedStepArray(raw[key]);
      }
    }
    if ('branches' in raw && !('branches' in step)) {
      const branches = raw.branches;
      if (Array.isArray(branches)) {
        step.branches = branches.map((branch) => {
          if (!branch || typeof branch !== 'object') return branch;
          const br = branch as Record<string, unknown>;
          if (!Array.isArray(br.steps)) return br;
          return {
            ...br,
            steps: normalizeNestedStepArray(br.steps)
          };
        });
      }
    }
  } else {
    step = { ...raw };
    if ('config' in step && !isNonEmptyConfig(step.config)) {
      delete step.config;
    }
  }

  for (const key of NESTED_STEP_KEYS) {
    if (key in step) {
      step[key] = normalizeNestedStepArray(step[key]);
    }
  }
  if (Array.isArray(step.branches)) {
    step.branches = step.branches.map((branch) => {
      if (!branch || typeof branch !== 'object') return branch;
      const br = branch as Record<string, unknown>;
      if (!Array.isArray(br.steps)) return br;
      return {
        ...br,
        steps: normalizeNestedStepArray(br.steps)
      };
    });
  }

  return step as FlowStep;
}

function graphNodesToFlowSteps(nodes: Record<string, unknown>[]): FlowStep[] {
  return [...nodes]
    .sort((a, b) => String(a.order ?? '').localeCompare(String(b.order ?? '')))
    .map((node) => {
      const config = (node.config ?? {}) as Record<string, unknown>;
      const rawType = String(node.type ?? config.type ?? 'unknown');
      const shortType = rawType.includes('.')
        ? rawType.split('.').pop()!
        : rawType;
      return {
        ...config,
        type: shortType,
        ...(node.id != null ? { id: node.id } : {})
      } as FlowStep;
    });
}

function isFlowgramDocument(nodes: unknown[]): boolean {
  const first = nodes[0];
  return (
    !!first &&
    typeof first === 'object' &&
    ('blocks' in (first as object) ||
      (first as { type?: string }).type === 'start')
  );
}

/** Best-effort steps for FlowEditor preview from org scenario / template body. */
export function extractPreviewSteps(
  body: Record<string, unknown> | null | undefined
): FlowStep[] {
  if (!body || typeof body !== 'object') return [];

  const steps = body.steps;
  if (Array.isArray(steps) && steps.length > 0) {
    return steps
      .filter((s): s is Record<string, unknown> => !!s && typeof s === 'object')
      .map(normalizeSequenceStep);
  }

  const nodes = body.nodes;
  if (!Array.isArray(nodes) || nodes.length === 0) return [];

  if (isFlowgramDocument(nodes)) {
    try {
      return flowDocToSteps({
        nodes,
        edges: Array.isArray(body.edges) ? body.edges : []
      } as FlowDocumentJSON);
    } catch {
      return [];
    }
  }

  return graphNodesToFlowSteps(
    nodes.filter(
      (n): n is Record<string, unknown> => !!n && typeof n === 'object'
    )
  );
}

function countNestedFlowSteps(step: FlowStep): number {
  let count = 1;
  const record = step as Record<string, unknown>;
  for (const key of NESTED_STEP_KEYS) {
    const nested = record[key];
    if (!Array.isArray(nested)) continue;
    count += nested
      .filter((s): s is FlowStep => !!s && typeof s === 'object')
      .reduce((sum, child) => sum + countNestedFlowSteps(child), 0);
  }
  const branches = record.branches;
  if (Array.isArray(branches)) {
    for (const branch of branches) {
      if (!branch || typeof branch !== 'object') continue;
      const branchSteps = (branch as Record<string, unknown>).steps;
      if (!Array.isArray(branchSteps)) continue;
      count += branchSteps
        .filter((s): s is FlowStep => !!s && typeof s === 'object')
        .reduce((sum, child) => sum + countNestedFlowSteps(child), 0);
    }
  }
  return count;
}

export function countPreviewSteps(steps: FlowStep[]): {
  topLevel: number;
  total: number;
} {
  return {
    topLevel: steps.length,
    total: steps.reduce((sum, step) => sum + countNestedFlowSteps(step), 0)
  };
}

export function countScenarioVariables(
  variables: Record<string, unknown> | null | undefined
): number {
  if (!variables || typeof variables !== 'object') return 0;
  return Object.keys(variables).length;
}
