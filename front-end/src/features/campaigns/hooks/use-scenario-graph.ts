import { useReducer, useCallback } from 'react';
import { generateKeyBetween } from 'fractional-indexing';
import { nanoid } from 'nanoid';
import {
  FlowNode,
  FlowEdge,
  NodeScope,
  getChildNodes,
  getRootNodes
} from '../components/scenario-steps/types';
import { createDefaultStep } from '../components/scenario-steps/types';

// ── State ─────────────────────────────────────────────────────────────────────

interface GraphState {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

// ── Actions ───────────────────────────────────────────────────────────────────

type GraphAction =
  | {
      type: 'ADD_NODE';
      node: FlowNode;
      afterNodeId?: string | null;
      scope?: NodeScope | null;
    }
  | { type: 'UPDATE_NODE'; id: string; patch: Partial<FlowNode> }
  | { type: 'UPDATE_NODE_CONFIG'; id: string; config: Record<string, unknown> }
  | { type: 'REMOVE_NODE'; id: string }
  | {
      type: 'MOVE_NODE';
      id: string;
      afterNodeId: string | null;
      newScope?: NodeScope | null;
    }
  | { type: 'RESET'; nodes: FlowNode[]; edges: FlowEdge[] };

// ── Helpers ───────────────────────────────────────────────────────────────────

function getSiblings(
  nodes: FlowNode[],
  scope: NodeScope | null | undefined
): FlowNode[] {
  if (!scope?.parentId) return getRootNodes(nodes);
  return getChildNodes(nodes, scope.parentId, scope.branch);
}

function calcOrder(
  nodes: FlowNode[],
  scope: NodeScope | null | undefined,
  afterNodeId?: string | null
): string {
  const siblings = getSiblings(nodes, scope);
  if (!siblings.length) return generateKeyBetween(null, null);
  if (!afterNodeId) {
    return generateKeyBetween(siblings[siblings.length - 1]!.order, null);
  }
  const idx = siblings.findIndex((n) => n.id === afterNodeId);
  if (idx === -1) {
    // afterNodeId not found in this scope — append at end instead of silently misplacing
    return generateKeyBetween(siblings[siblings.length - 1]!.order, null);
  }
  const prev = siblings[idx]!.order;
  const next = siblings[idx + 1]?.order ?? null;
  return generateKeyBetween(prev, next);
}

function wireEdgesForInsert(
  edges: FlowEdge[],
  newId: string,
  afterNodeId: string | null | undefined,
  siblings: FlowNode[]
): FlowEdge[] {
  if (!afterNodeId) {
    // Prepend: new → first existing sibling (if any)
    const first = siblings[0];
    if (!first) return edges;
    return [
      ...edges,
      {
        id: nanoid(10),
        source: newId,
        target: first.id,
        type: 'default' as const
      }
    ];
  }
  const afterIdx = siblings.findIndex((n) => n.id === afterNodeId);
  if (afterIdx === -1) return edges; // afterNode not in scope — skip edge wiring
  const afterNode = siblings[afterIdx]!;
  const nextNode = siblings[afterIdx + 1];

  // Remove afterNode → nextNode edge (we insert between them)
  const filtered = edges.filter(
    (e) => !(e.source === afterNode.id && e.target === (nextNode?.id ?? ''))
  );
  const newEdges: FlowEdge[] = [
    ...filtered,
    {
      id: nanoid(10),
      source: afterNode.id,
      target: newId,
      type: 'default' as const
    }
  ];
  if (nextNode) {
    newEdges.push({
      id: nanoid(10),
      source: newId,
      target: nextNode.id,
      type: 'default' as const
    });
  }
  return newEdges;
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state: GraphState, action: GraphAction): GraphState {
  switch (action.type) {
    case 'ADD_NODE': {
      const { node, afterNodeId, scope } = action;
      const siblings = getSiblings(state.nodes, scope);
      const newEdges = wireEdgesForInsert(
        state.edges,
        node.id,
        afterNodeId,
        siblings
      );
      return { nodes: [...state.nodes, node], edges: newEdges };
    }

    case 'UPDATE_NODE':
      return {
        ...state,
        nodes: state.nodes.map((n) =>
          n.id === action.id ? { ...n, ...action.patch } : n
        )
      };

    case 'UPDATE_NODE_CONFIG':
      return {
        ...state,
        nodes: state.nodes.map((n) =>
          n.id === action.id
            ? { ...n, config: { ...n.config, ...action.config } }
            : n
        )
      };

    case 'REMOVE_NODE': {
      // Collect node + all descendants
      const toRemove = new Set<string>();
      const queue = [action.id];
      while (queue.length) {
        const cur = queue.shift()!;
        toRemove.add(cur);
        state.nodes
          .filter((n) => n.scope?.parentId === cur)
          .forEach((n) => queue.push(n.id));
      }
      const nodes = state.nodes.filter((n) => !toRemove.has(n.id));
      // Reconnect predecessor → successor across the removed node
      const inEdge = state.edges.find((e) => e.target === action.id);
      const outEdge = state.edges.find((e) => e.source === action.id);
      const remaining = state.edges.filter(
        (e) => !toRemove.has(e.source) && !toRemove.has(e.target)
      );
      const edges =
        inEdge && outEdge
          ? [
              ...remaining,
              {
                id: nanoid(10),
                source: inEdge.source,
                target: outEdge.target,
                type: 'default' as const
              }
            ]
          : remaining;
      return { nodes, edges };
    }

    case 'MOVE_NODE': {
      const { id, afterNodeId, newScope } = action;
      const node = state.nodes.find((n) => n.id === id);
      if (!node) return state;
      const effectiveScope = newScope !== undefined ? newScope : node.scope;
      const nodesWithoutMoved = state.nodes.filter((n) => n.id !== id);
      const order = calcOrder(nodesWithoutMoved, effectiveScope, afterNodeId);

      // Rewire edges: remove old edges connected to this node, add new ones in target scope
      const oldInEdge = state.edges.find((e) => e.target === id);
      const oldOutEdge = state.edges.find((e) => e.source === id);

      // Patch the predecessor/successor gap left by the move
      let edges = state.edges.filter((e) => e.source !== id && e.target !== id);
      if (oldInEdge && oldOutEdge) {
        edges = [
          ...edges,
          {
            id: nanoid(10),
            source: oldInEdge.source,
            target: oldOutEdge.target,
            type: 'default' as const
          }
        ];
      }

      // Wire into target position
      const targetSiblings = getSiblings(nodesWithoutMoved, effectiveScope);
      edges = wireEdgesForInsert(edges, id, afterNodeId, targetSiblings);

      const nodes = nodesWithoutMoved
        .map((n) => n)
        .concat([
          {
            ...node,
            order,
            scope: effectiveScope ?? null
          }
        ]);

      return { nodes, edges };
    }

    case 'RESET':
      return { nodes: action.nodes, edges: action.edges };

    default:
      return state;
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export interface UseScenarioGraphReturn {
  nodes: FlowNode[];
  edges: FlowEdge[];
  addNode: (
    type: string,
    afterNodeId?: string | null,
    scope?: NodeScope | null
  ) => string;
  updateNode: (id: string, patch: Partial<FlowNode>) => void;
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void;
  removeNode: (id: string) => void;
  moveNode: (
    id: string,
    afterNodeId: string | null,
    newScope?: NodeScope | null
  ) => void;
  reset: (nodes: FlowNode[], edges: FlowEdge[]) => void;
}

export function useScenarioGraph(
  initialNodes: FlowNode[] = [],
  initialEdges: FlowEdge[] = []
): UseScenarioGraphReturn {
  const [state, dispatch] = useReducer(reducer, {
    nodes: initialNodes,
    edges: initialEdges
  });

  const addNode = useCallback(
    (
      type: string,
      afterNodeId?: string | null,
      scope?: NodeScope | null
    ): string => {
      const id = nanoid(10);
      // calcOrder needs current state — we compute it here, before dispatch
      const order = calcOrder(state.nodes, scope, afterNodeId);
      const defaultStep = createDefaultStep(type);
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const {
        type: _t,
        steps: _s,
        then: _th,
        else: _e,
        branches: _b,
        ...config
      } = defaultStep as Record<string, unknown>;
      const node: FlowNode = {
        id,
        type,
        config: config as Record<string, unknown>,
        order,
        scope: scope ?? null
      };
      dispatch({ type: 'ADD_NODE', node, afterNodeId, scope });
      return id;
    },
    [state.nodes]
  );

  const updateNode = useCallback(
    (id: string, patch: Partial<FlowNode>) =>
      dispatch({ type: 'UPDATE_NODE', id, patch }),
    []
  );

  const updateNodeConfig = useCallback(
    (id: string, config: Record<string, unknown>) =>
      dispatch({ type: 'UPDATE_NODE_CONFIG', id, config }),
    []
  );

  const removeNode = useCallback(
    (id: string) => dispatch({ type: 'REMOVE_NODE', id }),
    []
  );

  const moveNode = useCallback(
    (id: string, afterNodeId: string | null, newScope?: NodeScope | null) =>
      dispatch({ type: 'MOVE_NODE', id, afterNodeId, newScope }),
    []
  );

  const reset = useCallback(
    (nodes: FlowNode[], edges: FlowEdge[]) =>
      dispatch({ type: 'RESET', nodes, edges }),
    []
  );

  return {
    nodes: state.nodes,
    edges: state.edges,
    addNode,
    updateNode,
    updateNodeConfig,
    removeNode,
    moveNode,
    reset
  };
}
