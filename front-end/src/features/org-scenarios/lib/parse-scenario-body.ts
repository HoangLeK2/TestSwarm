import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';
import { flowDocToSteps } from '@/features/scenario-templates/components/scenario-flow-editor/converters';
import type { FlowDocumentJSON } from '@flowgram.ai/fixed-layout-editor';

function normalizeSequenceStep(raw: Record<string, unknown>): FlowStep {
  if (
    raw.type &&
    raw.config &&
    typeof raw.config === 'object' &&
    !Array.isArray(raw.config)
  ) {
    return {
      ...(raw.config as Record<string, unknown>),
      type: String(raw.type),
      ...(raw.id != null ? { id: raw.id } : {})
    } as FlowStep;
  }
  return raw as FlowStep;
}

function graphNodesToFlowSteps(nodes: Record<string, unknown>[]): FlowStep[] {
  return [...nodes]
    .sort((a, b) =>
      String(a.order ?? '').localeCompare(String(b.order ?? ''))
    )
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
    ('blocks' in (first as object) || (first as { type?: string }).type === 'start')
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
    nodes.filter((n): n is Record<string, unknown> => !!n && typeof n === 'object')
  );
}

export function countScenarioVariables(
  variables: Record<string, unknown> | null | undefined
): number {
  if (!variables || typeof variables !== 'object') return 0;
  return Object.keys(variables).length;
}
