import { useReducer, useCallback } from 'react';
import { generateKeyBetween } from 'fractional-indexing';
import { nanoid } from 'nanoid';
import type {
  FlowNode,
  FlowEdge,
  NodeScope
} from '../components/scenario-steps/types';
import { createDefaultStep } from '../components/scenario-steps/types';
import {
  getOrderedScopeNodes,
  insertScenarioNode,
  moveScenarioNode,
  rebuildScenarioSequenceEdges
} from '../utils/scenario-graph';

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

function appendOrder(
  nodes: FlowNode[],
  scope: NodeScope | null | undefined
): string {
  const siblings = getOrderedScopeNodes(nodes, scope);
  return generateKeyBetween(siblings.at(-1)?.order ?? null, null);
}

function appendAfterNodeId(
  nodes: FlowNode[],
  scope: NodeScope | null | undefined
): string | null {
  return getOrderedScopeNodes(nodes, scope).at(-1)?.id ?? null;
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state: GraphState, action: GraphAction): GraphState {
  switch (action.type) {
    case 'ADD_NODE': {
      const { node, afterNodeId, scope } = action;
      return (
        insertScenarioNode(state, node, scope ?? null, afterNodeId ?? null) ??
        state
      );
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
      const remainingEdges = state.edges.filter(
        (edge) => !toRemove.has(edge.source) && !toRemove.has(edge.target)
      );
      return {
        nodes,
        edges: rebuildScenarioSequenceEdges(nodes, remainingEdges)
      };
    }

    case 'MOVE_NODE': {
      const node = state.nodes.find((candidate) => candidate.id === action.id);
      if (!node) return state;
      const effectiveScope =
        action.newScope !== undefined ? action.newScope : (node.scope ?? null);
      return (
        moveScenarioNode(
          state,
          action.id,
          effectiveScope ?? null,
          action.afterNodeId
        ) ?? state
      );
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
      const effectiveAfterNodeId =
        afterNodeId === undefined
          ? appendAfterNodeId(state.nodes, scope)
          : afterNodeId;
      const order = appendOrder(state.nodes, scope);
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
      dispatch({
        type: 'ADD_NODE',
        node,
        afterNodeId: effectiveAfterNodeId,
        scope
      });
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
