type FlowNodeLike = {
  id: string;
  flowNodeType: unknown;
  parent?: FlowNodeLike | null;
};

const NON_SCENARIO_NODE_TYPES = new Set([
  'root',
  'start',
  'end',
  'block',
  'blockIcon',
  'blockOrderIcon',
  'inlineBlocks',
  'loopLeftEmptyBlock',
  'loopEmptyBranch'
]);

const SEQUENCE_PARENT_TYPES = new Set(['root', 'block']);

function isDescendantOfAny(
  node: FlowNodeLike | null | undefined,
  possibleAncestors: Set<string>
): boolean {
  let current = node;

  while (current) {
    if (possibleAncestors.has(current.id)) return true;
    current = current.parent;
  }

  return false;
}

/**
 * Flowgram passes the transition owner as `dropNode`, not necessarily a real
 * scenario node. Empty dynamic branches use `blockOrderIcon`; empty loop
 * bodies use `loopEmptyBranch`. Both are valid anchors because their parent is
 * the real sequence container (`block`).
 */
export function canDropScenarioNodes({
  dragNodes,
  dropNode
}: {
  dragNodes?: FlowNodeLike[];
  dropNode: FlowNodeLike;
}): boolean {
  if (!dragNodes?.length) return false;

  if (
    dragNodes.some(
      (node) =>
        node.id.startsWith('$') ||
        NON_SCENARIO_NODE_TYPES.has(String(node.flowNodeType))
    )
  ) {
    return false;
  }

  if (dropNode.flowNodeType === 'end') return false;

  const destinationParent = dropNode.parent;
  if (
    !destinationParent ||
    !SEQUENCE_PARENT_TYPES.has(String(destinationParent.flowNodeType))
  ) {
    return false;
  }

  const draggedIds = new Set(dragNodes.map((node) => node.id));
  return !isDescendantOfAny(destinationParent, draggedIds);
}
