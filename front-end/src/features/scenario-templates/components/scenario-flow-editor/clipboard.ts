import type { FlowNodeJSON } from '@flowgram.ai/fixed-layout-editor';

const SCENARIO_CLIPBOARD_KIND = 'device-farm/scenario-flow-nodes';
const SCENARIO_CLIPBOARD_VERSION = 1;

type ScenarioClipboardPayload = {
  kind: typeof SCENARIO_CLIPBOARD_KIND;
  version: typeof SCENARIO_CLIPBOARD_VERSION;
  nodes: FlowNodeJSON[];
};

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function isFlowNodeJson(value: unknown): value is FlowNodeJSON {
  if (!value || typeof value !== 'object') return false;
  const node = value as Partial<FlowNodeJSON>;
  return typeof node.id === 'string' && node.id.length > 0 && node.type != null;
}

export function serializeScenarioClipboardNodes(nodes: FlowNodeJSON[]): string {
  const payload: ScenarioClipboardPayload = {
    kind: SCENARIO_CLIPBOARD_KIND,
    version: SCENARIO_CLIPBOARD_VERSION,
    nodes: cloneJson(nodes)
  };
  return JSON.stringify(payload);
}

export function parseScenarioClipboardNodes(
  text: string
): FlowNodeJSON[] | null {
  try {
    const payload = JSON.parse(text) as Partial<ScenarioClipboardPayload>;
    if (
      payload.kind !== SCENARIO_CLIPBOARD_KIND ||
      payload.version !== SCENARIO_CLIPBOARD_VERSION ||
      !Array.isArray(payload.nodes) ||
      !payload.nodes.every(isFlowNodeJson)
    ) {
      return null;
    }
    return cloneJson(payload.nodes);
  } catch {
    return null;
  }
}

function cloneNodeWithNewIds(
  node: FlowNodeJSON,
  generateId: () => string,
  forcedId?: string
): FlowNodeJSON {
  const oldId = node.id;
  const newId = forcedId ?? generateId();
  const data = cloneJson(node.data ?? {});
  const step = data?.step;
  if (step && typeof step === 'object') {
    data.step = {
      ...(step as Record<string, unknown>),
      id: newId,
      _fgId: newId
    };
  }

  return {
    ...cloneJson(node),
    id: newId,
    data,
    blocks: (node.blocks ?? []).map((block, index) => {
      const isStructuralBlock = block.type === 'block';
      const blockId = isStructuralBlock
        ? block.id.startsWith(oldId)
          ? `${newId}${block.id.slice(oldId.length)}`
          : `${newId}_block_${index}`
        : undefined;
      return cloneNodeWithNewIds(block, generateId, blockId);
    })
  };
}

export function regenerateScenarioClipboardNodeIds(
  nodes: FlowNodeJSON[],
  generateId: () => string
): FlowNodeJSON[] {
  return nodes.map((node) => cloneNodeWithNewIds(node, generateId));
}
