/**
 * Converts between our FlowStep[] format and the flowgram.ai FlowDocumentJSON format.
 */
import type {
  FlowDocumentJSON,
  FlowNodeJSON
} from '@flowgram.ai/fixed-layout-editor';
import { generateNKeysBetween } from 'fractional-indexing';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

let _counter = 0;
const newId = (prefix = 'n') => `${prefix}_${_counter++}`;

function resetCounter() {
  _counter = 0;
}

function fgIdFromStep(step: FlowStep): string {
  const canonicalId = (step as Record<string, unknown>).id;
  if (typeof canonicalId === 'string' && canonicalId.trim()) {
    return canonicalId;
  }

  const legacyId = (step as Record<string, unknown>)._fgId;
  return typeof legacyId === 'string' && legacyId.trim() ? legacyId : newId();
}

function hasArrayField(step: FlowStep, key: 'then' | 'else' | 'steps') {
  return Array.isArray((step as Record<string, unknown>)[key]);
}

function hasThenElseBlocks(step: FlowStep): boolean {
  return (
    step.type === 'if' ||
    step.type === 'if_element' ||
    step.type === 'if_variable' ||
    step.type === 'social_open_comments' ||
    step.type === 'social_open_comments' ||
    hasArrayField(step, 'then') ||
    hasArrayField(step, 'else')
  );
}

function hasBranchBlocks(step: FlowStep): boolean {
  return step.type === 'random_pick' || Array.isArray((step as any).branches);
}

function hasLoopBody(step: FlowStep): boolean {
  return (
    step.type === 'repeat' ||
    step.type === 'repeat_until' ||
    step.type === 'loop' ||
    hasArrayField(step, 'steps')
  );
}

function thenElseTitles(step: FlowStep): [string, string] {
  const isFbTap =
    step.type === 'social_open_comments' ||
    step.type === 'social_open_comments';
  if (isFbTap) {
    return ['Khi bấm được nút Bình luận', 'Khi không thấy nút Bình luận'];
  }
  return ['Nếu đúng (then)', 'Nếu sai (else)'];
}

// ─── steps → FlowDocumentJSON ─────────────────────────────────────────────────

export function stepToFlowNode(step: FlowStep): FlowNodeJSON {
  const id = fgIdFromStep(step);

  // Condition-like steps with then/else branches.
  if (hasThenElseBlocks(step)) {
    const thenNodes = stepsToNodes((step as any).then ?? []);
    const elseNodes = stepsToNodes((step as any).else ?? []);
    const [thenTitle, elseTitle] = thenElseTitles(step);
    return {
      id,
      type: 'condition',
      data: { step },
      blocks: [
        {
          id: `${id}_then`,
          type: 'block',
          data: { title: thenTitle },
          blocks: thenNodes
        },
        {
          id: `${id}_else`,
          type: 'block',
          data: { title: elseTitle },
          blocks: elseNodes
        }
      ]
    };
  }

  // Random pick (multiple branches)
  if (hasBranchBlocks(step)) {
    const branches: FlowNodeJSON[] = ((step as any).branches ?? []).map(
      (branch: { weight?: number; steps: FlowStep[] }, i: number) => ({
        id: `${id}_branch_${i}`,
        type: 'block',
        data: {
          title: `Nhánh ${i + 1} (${branch.weight ?? 1})`,
          weight: branch.weight ?? 1
        },
        blocks: stepsToNodes(branch.steps ?? [])
      })
    );
    const paddedBranches =
      branches.length >= 2
        ? branches
        : [
            ...branches,
            ...Array.from({ length: 2 - branches.length }, (_, i) => {
              const branchIndex = branches.length + i;
              return {
                id: `${id}_branch_${branchIndex}`,
                type: 'block',
                data: {
                  title: `Nhánh ${branchIndex + 1}`,
                  weight: 1,
                  synthetic: true
                },
                blocks: []
              };
            })
          ];
    return {
      id,
      type: 'condition',
      data: { step },
      blocks: paddedBranches
    };
  }

  // Loop (repeat / repeat_until / loop)
  if (hasLoopBody(step)) {
    return {
      id,
      type: 'loop_node',
      data: { step },
      // Native LoopRegistry mounts these nodes directly inside its loop body.
      // Adding another `block` here creates a fake nested scope and prevents
      // native drag/drop from targeting the real loop body.
      blocks: stepsToNodes((step as any).steps ?? [])
    };
  }

  // Default: action node
  return {
    id,
    type: step.type === 'run_scenario' ? 'sub_scenario' : 'action',
    data: { step }
  };
}

function stepsToNodes(steps: FlowStep[]): FlowNodeJSON[] {
  return steps.map((s) => stepToFlowNode(s));
}

export function stepsToFlowDoc(steps: FlowStep[]): FlowDocumentJSON {
  resetCounter();
  return {
    nodes: [
      { id: 'start_0', type: 'start', data: { title: 'Bắt đầu' }, blocks: [] },
      ...stepsToNodes(steps),
      { id: 'end_0', type: 'end', data: { title: 'Kết thúc' } }
    ]
  };
}

// ─── FlowDocumentJSON → steps ─────────────────────────────────────────────────

function withFlowgramIdentity<S extends FlowStep>(nodeId: string, step: S): S {
  return { ...step, id: nodeId, _fgId: nodeId } as S;
}

function nodeToStep(node: FlowNodeJSON): FlowStep | null {
  if (node.type === 'start' || node.type === 'end' || node.type === 'block')
    return null;

  const step = node.data?.step as FlowStep | undefined;
  if (!step) return null;

  // Reconstruct nested steps from blocks
  if (hasThenElseBlocks(step)) {
    const thenBlock = node.blocks?.[0];
    const elseBlock = node.blocks?.[1];
    return withFlowgramIdentity(node.id, {
      ...step,
      then: nodesToSteps(thenBlock?.blocks ?? []),
      else: nodesToSteps(elseBlock?.blocks ?? [])
    } as FlowStep);
  }

  if (hasBranchBlocks(step)) {
    const branches = (node.blocks ?? []).flatMap((block) => {
      const data = block.data as { weight?: number; synthetic?: boolean };
      const steps = nodesToSteps(block.blocks ?? []);
      if (data?.synthetic && steps.length === 0) return [];
      return [
        {
          weight: data?.weight ?? 1,
          steps
        }
      ];
    });
    return withFlowgramIdentity(node.id, { ...step, branches } as FlowStep);
  }

  if (hasLoopBody(step)) {
    return withFlowgramIdentity(node.id, {
      ...step,
      steps: nodesToSteps(node.blocks ?? [])
    } as FlowStep);
  }

  return withFlowgramIdentity(node.id, step);
}

function nodesToSteps(nodes: FlowNodeJSON[]): FlowStep[] {
  const steps = nodes.flatMap((node) => {
    const step = nodeToStep(node);
    return step ? [step] : [];
  });
  const generatedOrders = generateNKeysBetween(null, null, steps.length);

  return steps.map((step, index) => ({
    ...step,
    order: generatedOrders[index]
  }));
}

export function flowDocToSteps(doc: FlowDocumentJSON): FlowStep[] {
  // Top-level nodes, excluding start/end
  const contentNodes = doc.nodes.filter(
    (n) => n.type !== 'start' && n.type !== 'end'
  );
  return nodesToSteps(contentNodes);
}
