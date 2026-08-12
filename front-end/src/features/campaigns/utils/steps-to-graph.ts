/**
 * steps-to-graph.ts
 * Frontend port of device_farm/common/graph_compiler.py steps_to_graph().
 * Converts flat steps[] → { nodes, edges } for the graph model.
 *
 * NOTE: `description` is intentionally kept in node.config (not promoted to
 * node.description) because step types use it as a regular config field.
 * Only `type`, structural array keys (steps/then/else/branches/else_steps),
 * and `title` are stripped from config.
 */
import { generateNKeysBetween } from 'fractional-indexing';
import { nanoid } from 'nanoid';
import type { FlowNode, FlowEdge } from '../components/scenario-steps/types';

// Keys stripped from config (handled as child-node scopes or top-level node fields).
// NOTE: `description` is NOT in this list — it stays in config.
const STRIP_FROM_CONFIG = new Set([
  'type',
  'title',
  'steps',
  'then',
  'else',
  'branches',
  'else_steps',
  'id',
  'order',
  '_id',
  '_fgId'
]);

const CONTAINER_STEP_TYPES = new Set(['loop', 'repeat', 'repeat_until']);
const CONTAINER_IF_TYPES = new Set([
  'if',
  'if_element',
  'if_variable',
  'fb_tap_comment_button',
  'tap_fb_comment_button'
]);

export function stepsToGraph(steps: Record<string, unknown>[]): {
  nodes: FlowNode[];
  edges: FlowEdge[];
} {
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];

  function walk(
    stepList: Record<string, unknown>[],
    parentScope: FlowNode['scope']
  ): void {
    if (!stepList.length) return;
    const orders = generateNKeysBetween(null, null, stepList.length);

    let prevId: string | null = null;

    stepList.forEach((step, i) => {
      const id =
        typeof step.id === 'string' && step.id.trim() ? step.id : nanoid(10);
      const type = String(step.type ?? 'unknown');

      // Build config — strip structural keys and type; keep everything else including description
      const config: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(step)) {
        if (!STRIP_FROM_CONFIG.has(k)) config[k] = v;
      }

      // Store branch weights as ordered list for stable round-trip
      if (type === 'random_pick') {
        const branches = (step.branches ?? []) as Array<
          Record<string, unknown>
        >;
        config['branch_weights'] = branches.map((b) => b['weight'] ?? 1);
        // Remove legacy per-index weight keys if present
        delete config['branch_count'];
      }

      const node: FlowNode = {
        id,
        type,
        config,
        order:
          typeof step.order === 'string' && step.order
            ? step.order
            : orders[i]!,
        scope: parentScope ?? null,
        ...(step.title ? { title: String(step.title) } : {})
      };
      nodes.push(node);

      if (prevId) {
        edges.push({
          id: nanoid(10),
          source: prevId,
          target: id,
          type: 'default'
        });
      }
      prevId = id;

      // Recurse into child branches
      if (CONTAINER_STEP_TYPES.has(type)) {
        walk((step.steps ?? []) as Record<string, unknown>[], {
          parentId: id,
          branch: 'steps'
        });
      } else if (CONTAINER_IF_TYPES.has(type)) {
        walk((step.then ?? []) as Record<string, unknown>[], {
          parentId: id,
          branch: 'then'
        });
        const elseSteps = (step.else ?? step.else_steps ?? []) as Record<
          string,
          unknown
        >[];
        if (elseSteps.length) {
          walk(elseSteps, { parentId: id, branch: 'else' });
        }
      } else if (type === 'random_pick') {
        const branches = (step.branches ?? []) as Array<
          Record<string, unknown>
        >;
        branches.forEach((branch, bi) => {
          // Always create scope for every branch — even empty ones — so branch
          // count is preserved across round-trips (empty branch ≠ deleted branch).
          walk((branch.steps ?? []) as Record<string, unknown>[], {
            parentId: id,
            branch: `branch_${bi}`
          });
        });
      }
    });
  }

  walk(steps, null);
  return { nodes, edges };
}
