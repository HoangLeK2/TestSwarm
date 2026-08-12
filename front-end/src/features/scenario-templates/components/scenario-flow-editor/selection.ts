const EDITABLE_FLOW_NODE_TYPES = new Set([
  'action',
  'sub_scenario',
  'condition',
  'loop_node'
]);

export type FlowgramSelectionEntity = {
  id: string;
  flowNodeType: string | number;
};

export function getSingleEditableFlowNodeId(
  selection: readonly unknown[]
): string | null {
  if (selection.length !== 1) return null;

  const entity = selection[0] as Partial<FlowgramSelectionEntity> | undefined;
  if (
    typeof entity?.id !== 'string' ||
    typeof entity.flowNodeType !== 'string' ||
    !EDITABLE_FLOW_NODE_TYPES.has(entity.flowNodeType)
  ) {
    return null;
  }

  return entity.id;
}
