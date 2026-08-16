import ELK from 'elkjs/lib/elk.bundled.js';
import type { ElkExtendedEdge, ElkNode, ElkPoint } from 'elkjs/lib/elk-api';

import type {
  FlowEdge,
  FlowNode,
  FlowStep,
  NodeScope
} from '@/features/campaigns/components/scenario-steps/types';
import { getOrderedScopeNodes } from '@/features/campaigns/utils/scenario-graph';

export const SCENARIO_NODE_WIDTH = 232;
export const SCENARIO_NODE_HEIGHT = 64;
export const SCENARIO_START_ID = 'scenario-start';
export const SCENARIO_END_ID = 'scenario-end';

const ANCHOR_WIDTH = 132;
const ANCHOR_HEIGHT = 52;
const PLACEHOLDER_WIDTH = 176;
const PLACEHOLDER_HEIGHT = 48;
const JUNCTION_SIZE = 12;
const FRAME_PADDING_X = 24;
const FRAME_PADDING_TOP = 38;
const FRAME_PADDING_BOTTOM = 22;

export type ScenarioLaneTone = 'amber' | 'sky' | 'rose';

export type ScenarioLayoutNode = {
  id: string;
  kind: 'step' | 'anchor' | 'placeholder' | 'junction' | 'frame';
  position: { x: number; y: number };
  width: number;
  height: number;
  nodeId?: string;
  scope?: NodeScope | null;
  index?: number;
  siblingCount?: number;
  previousNodeId?: string | null;
  moveBackAfterNodeId?: string | null;
  moveForwardAfterNodeId?: string | null;
  step?: FlowStep;
  title?: string;
  subtitle?: string;
  label?: string;
  tone?: ScenarioLaneTone;
};

export type ScenarioLayoutEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  points: ElkPoint[];
};

export type ScenarioLayout = {
  nodes: ScenarioLayoutNode[];
  edges: ScenarioLayoutEdge[];
  width: number;
  height: number;
};

type NodeMeta = Omit<ScenarioLayoutNode, 'position'>;

type LaneRecord = {
  id: string;
  title: string;
  subtitle: string;
  tone: ScenarioLaneTone;
  nodeIds: string[];
};

type BuildResult = {
  lastNodeId: string;
  nodeIds: string[];
};

type BuildContext = {
  graphNodes: FlowNode[];
  nodes: ElkNode[];
  edges: ElkExtendedEdge[];
  metaById: Map<string, NodeMeta>;
  lanes: LaneRecord[];
  edgeIndex: number;
  junctionIndex: number;
};

type ChildContainer = {
  scope: NodeScope;
  nodes: FlowNode[];
  title: string;
  subtitle: string;
  edgeLabel: string;
  tone: ScenarioLaneTone;
};

const elk = new ELK();

export function scenarioStepNodeId(nodeId: string): string {
  return nodeId;
}

export function countScenarioSteps(nodes: FlowNode[] | undefined): number {
  return Array.isArray(nodes) ? nodes.length : 0;
}

function addNode(ctx: BuildContext, meta: NodeMeta) {
  ctx.metaById.set(meta.id, meta);
  ctx.nodes.push({ id: meta.id, width: meta.width, height: meta.height });
}

function addEdge(
  ctx: BuildContext,
  source: string,
  target: string,
  label?: string
) {
  const id = `layout-edge:${ctx.edgeIndex++}:${source}->${target}`;
  ctx.edges.push({
    id,
    sources: [source],
    targets: [target],
    labels: label
      ? [{ text: label, width: Math.max(42, label.length * 6.5), height: 18 }]
      : undefined
  });
}

function branchCount(node: FlowNode, nodes: FlowNode[]): number {
  const weights = Array.isArray(node.config.branch_weights)
    ? node.config.branch_weights
    : [];
  let count = weights.length;
  for (const candidate of nodes) {
    if (candidate.scope?.parentId !== node.id) continue;
    const match = /^branch_(\d+)$/.exec(candidate.scope.branch);
    if (match) count = Math.max(count, Number(match[1]) + 1);
  }
  return count;
}

function childContainers(ctx: BuildContext, node: FlowNode): ChildContainer[] {
  const childScope = (branch: string): NodeScope => ({
    parentId: node.id,
    branch
  });
  const ordered = (scope: NodeScope) =>
    getOrderedScopeNodes(ctx.graphNodes, scope);

  if (
    [
      'if',
      'if_element',
      'if_variable',
      'social_open_comments',
      'social_open_comments'
    ].includes(node.type)
  ) {
    const thenScope = childScope('then');
    const elseScope = childScope('else');
    const thenNodes = ordered(thenScope);
    const elseNodes = ordered(elseScope);
    return [
      {
        scope: thenScope,
        nodes: thenNodes,
        title: 'Nếu đúng',
        subtitle: `${thenNodes.length} bước`,
        edgeLabel: 'Đúng',
        tone: 'amber'
      },
      {
        scope: elseScope,
        nodes: elseNodes,
        title: 'Nếu sai',
        subtitle: `${elseNodes.length} bước`,
        edgeLabel: 'Sai',
        tone: 'amber'
      }
    ];
  }

  if (node.type === 'random_pick') {
    const weights = Array.isArray(node.config.branch_weights)
      ? node.config.branch_weights
      : [];
    return Array.from(
      { length: branchCount(node, ctx.graphNodes) },
      (_, index) => {
        const scope = childScope(`branch_${index}`);
        return {
          scope,
          nodes: ordered(scope),
          title: `Nhánh ${index + 1}`,
          subtitle: `Trọng số ${weights[index] ?? 1}`,
          edgeLabel: `Nhánh ${index + 1}`,
          tone: 'rose' as const
        };
      }
    );
  }

  if (['loop', 'repeat', 'repeat_until'].includes(node.type)) {
    const scope = childScope('steps');
    const childNodes = ordered(scope);
    return [
      {
        scope,
        nodes: childNodes,
        title: 'Thân vòng lặp',
        subtitle: `${childNodes.length} bước`,
        edgeLabel: 'Lặp',
        tone: 'sky'
      }
    ];
  }

  return [];
}

function nodeToStep(node: FlowNode, containers: ChildContainer[]): FlowStep {
  const { branch_weights: _branchWeights, ...config } = node.config;
  const step: FlowStep = {
    ...config,
    type: node.type,
    id: node.id,
    order: node.order
  };
  if (node.title) step.title = node.title;
  if (node.description) step.description = node.description;

  if (containers.length > 0) {
    if (node.type === 'random_pick') {
      step.branches = containers.map((container, index) => ({
        weight: Array.isArray(node.config.branch_weights)
          ? (node.config.branch_weights[index] ?? 1)
          : 1,
        steps: container.nodes.map((child) => ({ type: child.type }))
      }));
    } else if (
      containers.some((container) => container.scope.branch === 'then')
    ) {
      step.then =
        containers.find((item) => item.scope.branch === 'then')?.nodes ?? [];
      step.else =
        containers.find((item) => item.scope.branch === 'else')?.nodes ?? [];
    } else {
      step.steps = containers[0]?.nodes ?? [];
    }
  }

  return step;
}

function scopeKey(scope: NodeScope | null): string {
  return scope ? `${scope.parentId}:${scope.branch}` : 'root';
}

function buildSequence(
  ctx: BuildContext,
  nodes: FlowNode[],
  scope: NodeScope | null,
  incomingNodeId: string,
  incomingLabel?: string
): BuildResult {
  if (nodes.length === 0) {
    const id = `placeholder:${scopeKey(scope)}`;
    addNode(ctx, {
      id,
      kind: 'placeholder',
      width: PLACEHOLDER_WIDTH,
      height: PLACEHOLDER_HEIGHT,
      scope,
      index: 0,
      label: 'Thêm bước đầu tiên'
    });
    addEdge(ctx, incomingNodeId, id, incomingLabel);
    return { lastNodeId: id, nodeIds: [id] };
  }

  let previousNodeId = incomingNodeId;
  const allNodeIds: string[] = [];

  nodes.forEach((node, index) => {
    const id = scenarioStepNodeId(node.id);
    const containers = childContainers(ctx, node);
    addNode(ctx, {
      id,
      kind: 'step',
      width: SCENARIO_NODE_WIDTH,
      height: SCENARIO_NODE_HEIGHT,
      nodeId: node.id,
      scope,
      index,
      siblingCount: nodes.length,
      previousNodeId: nodes[index - 1]?.id ?? null,
      moveBackAfterNodeId: index > 1 ? (nodes[index - 2]?.id ?? null) : null,
      moveForwardAfterNodeId: nodes[index + 1]?.id ?? null,
      step: nodeToStep(node, containers)
    });
    addEdge(ctx, previousNodeId, id, index === 0 ? incomingLabel : undefined);
    allNodeIds.push(id);

    if (containers.length === 0) {
      previousNodeId = id;
      return;
    }

    const laneResults = containers.map((container) => {
      const result = buildSequence(
        ctx,
        container.nodes,
        container.scope,
        id,
        container.edgeLabel
      );
      ctx.lanes.push({
        id: `frame:${scopeKey(container.scope)}`,
        title: container.title,
        subtitle: container.subtitle,
        tone: container.tone,
        nodeIds: result.nodeIds
      });
      allNodeIds.push(...result.nodeIds);
      return result;
    });

    const junctionId = `junction:${node.id}:${ctx.junctionIndex++}`;
    addNode(ctx, {
      id: junctionId,
      kind: 'junction',
      width: JUNCTION_SIZE,
      height: JUNCTION_SIZE
    });
    laneResults.forEach((result) =>
      addEdge(ctx, result.lastNodeId, junctionId)
    );
    allNodeIds.push(junctionId);
    previousNodeId = junctionId;
  });

  return { lastNodeId: previousNodeId, nodeIds: allNodeIds };
}

function edgePoints(edge: ElkExtendedEdge): ElkPoint[] {
  const section = edge.sections?.[0];
  if (!section) return [];
  return [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
}

function frameFromLane(
  lane: LaneRecord,
  positionedById: Map<string, ScenarioLayoutNode>
): ScenarioLayoutNode | null {
  const nodes = lane.nodeIds
    .map((id) => positionedById.get(id))
    .filter((node): node is ScenarioLayoutNode => Boolean(node));
  if (nodes.length === 0) return null;

  const left = Math.min(...nodes.map((node) => node.position.x));
  const top = Math.min(...nodes.map((node) => node.position.y));
  const right = Math.max(...nodes.map((node) => node.position.x + node.width));
  const bottom = Math.max(
    ...nodes.map((node) => node.position.y + node.height)
  );

  return {
    id: lane.id,
    kind: 'frame',
    position: {
      x: left - FRAME_PADDING_X,
      y: top - FRAME_PADDING_TOP
    },
    width: right - left + FRAME_PADDING_X * 2,
    height: bottom - top + FRAME_PADDING_TOP + FRAME_PADDING_BOTTOM,
    title: lane.title,
    subtitle: lane.subtitle,
    tone: lane.tone
  };
}

export async function layoutScenarioAutomation(
  graphNodes: FlowNode[],
  _graphEdges: FlowEdge[] = []
): Promise<ScenarioLayout> {
  const ctx: BuildContext = {
    graphNodes,
    nodes: [],
    edges: [],
    metaById: new Map(),
    lanes: [],
    edgeIndex: 0,
    junctionIndex: 0
  };

  addNode(ctx, {
    id: SCENARIO_START_ID,
    kind: 'anchor',
    width: ANCHOR_WIDTH,
    height: ANCHOR_HEIGHT,
    title: 'Bắt đầu',
    subtitle: 'Luồng thực thi'
  });
  addNode(ctx, {
    id: SCENARIO_END_ID,
    kind: 'anchor',
    width: ANCHOR_WIDTH,
    height: ANCHOR_HEIGHT,
    title: 'Kết thúc',
    subtitle: 'Hoàn tất kịch bản'
  });

  const sequence = buildSequence(
    ctx,
    getOrderedScopeNodes(graphNodes, null),
    null,
    SCENARIO_START_ID
  );
  addEdge(ctx, sequence.lastNodeId, SCENARIO_END_ID);

  const graph = await elk.layout({
    id: 'scenario-automation-root',
    children: ctx.nodes,
    edges: ctx.edges,
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.padding': '[top=56,left=56,bottom=56,right=56]',
      'elk.spacing.nodeNode': '42',
      'elk.layered.spacing.nodeNodeBetweenLayers': '92',
      'elk.layered.spacing.edgeNodeBetweenLayers': '36',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
      'elk.layered.crossingMinimization.semiInteractive': 'true'
    }
  });

  const positioned = (graph.children ?? []).map((node) => {
    const meta = ctx.metaById.get(node.id);
    if (!meta)
      throw new Error(`Missing scenario layout metadata for ${node.id}`);
    return {
      ...meta,
      position: { x: node.x ?? 0, y: node.y ?? 0 },
      width: node.width ?? meta.width,
      height: node.height ?? meta.height
    } satisfies ScenarioLayoutNode;
  });
  const positionedById = new Map(positioned.map((node) => [node.id, node]));
  const frames = ctx.lanes
    .map((lane) => frameFromLane(lane, positionedById))
    .filter((node): node is ScenarioLayoutNode => Boolean(node));

  return {
    nodes: [...frames, ...positioned],
    edges: (graph.edges ?? []).map((edge) => ({
      id: edge.id,
      source: edge.sources[0],
      target: edge.targets[0],
      label: edge.labels?.[0]?.text,
      points: edgePoints(edge)
    })),
    width: graph.width ?? 0,
    height: graph.height ?? 0
  };
}
