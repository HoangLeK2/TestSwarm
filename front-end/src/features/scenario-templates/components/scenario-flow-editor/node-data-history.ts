import type {
  FixedLayoutPluginContext,
  Operation,
  OperationMeta,
  StackOperation
} from '@flowgram.ai/fixed-layout-editor';

import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

export const UPDATE_SCENARIO_NODE_DATA = 'updateScenarioNodeData';

const MERGE_WINDOW_MS = 800;

type ScenarioNodeData = Record<string, unknown>;

export type UpdateScenarioNodeDataValue = {
  nodeId: string;
  oldData: ScenarioNodeData;
  newData: ScenarioNodeData;
};

export type UpdateScenarioNodeDataOperation =
  Operation<UpdateScenarioNodeDataValue>;

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function createUpdateScenarioNodeDataOperation(
  nodeId: string,
  oldData: ScenarioNodeData,
  newData: ScenarioNodeData
): UpdateScenarioNodeDataOperation {
  return {
    type: UPDATE_SCENARIO_NODE_DATA,
    value: {
      nodeId,
      oldData: cloneJson(oldData),
      newData: cloneJson(newData)
    }
  };
}

export function invertUpdateScenarioNodeDataOperation(
  operation: UpdateScenarioNodeDataOperation
): UpdateScenarioNodeDataOperation {
  return {
    ...operation,
    value: {
      nodeId: operation.value.nodeId,
      oldData: operation.value.newData,
      newData: operation.value.oldData
    }
  };
}

export function mergeUpdateScenarioNodeDataOperations(
  operation: UpdateScenarioNodeDataOperation,
  previous: Operation<UpdateScenarioNodeDataValue> | undefined,
  elapsedMs: number
): UpdateScenarioNodeDataOperation | false {
  if (
    previous?.type !== UPDATE_SCENARIO_NODE_DATA ||
    previous.value.nodeId !== operation.value.nodeId ||
    elapsedMs > MERGE_WINDOW_MS
  ) {
    return false;
  }

  return {
    ...operation,
    value: {
      nodeId: operation.value.nodeId,
      oldData: previous.value.oldData,
      newData: operation.value.newData
    }
  };
}

export function applyUpdateScenarioNodeDataOperation(
  operation: UpdateScenarioNodeDataOperation,
  ctx: FixedLayoutPluginContext
): boolean {
  const node = ctx.document.getNode(operation.value.nodeId);
  if (!node) return false;

  node.updateExtInfo(cloneJson(operation.value.newData), true);
  return true;
}

export const updateScenarioNodeDataOperationMeta: OperationMeta<
  UpdateScenarioNodeDataValue,
  FixedLayoutPluginContext,
  boolean
> = {
  type: UPDATE_SCENARIO_NODE_DATA,
  inverse: invertUpdateScenarioNodeDataOperation,
  shouldMerge(operation, previous, stackItem: StackOperation) {
    return mergeUpdateScenarioNodeDataOperations(
      operation,
      previous,
      Date.now() - stackItem.getTimestamp()
    );
  },
  apply: applyUpdateScenarioNodeDataOperation,
  getLabel: () => 'Update scenario step',
  getDescription: (operation) =>
    `Update scenario node ${operation.value.nodeId}`
};

export function pushScenarioNodeDataUpdate(
  ctx: FixedLayoutPluginContext,
  nodeId: string,
  nextStep: FlowStep
): boolean {
  const node = ctx.document.getNode(nodeId);
  if (!node) return false;

  const oldData = cloneJson(node.getExtInfo<ScenarioNodeData>() ?? {});
  const nextStepWithIdentity = {
    ...cloneJson(nextStep),
    id: nodeId,
    _fgId: nodeId
  } as FlowStep;
  const newData = {
    ...oldData,
    step: nextStepWithIdentity
  };

  if (JSON.stringify(oldData) === JSON.stringify(newData)) return false;

  ctx.history.pushOperation(
    createUpdateScenarioNodeDataOperation(nodeId, oldData, newData)
  );
  return true;
}
