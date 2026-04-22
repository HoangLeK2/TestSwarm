/**
 * Converts between our FlowStep[] format and the flowgram.ai FlowDocumentJSON format.
 */
import type { FlowDocumentJSON, FlowNodeJSON } from '@flowgram.ai/fixed-layout-editor';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

let _counter = 0;
const newId = (prefix = 'n') => `${prefix}_${_counter++}`;

function resetCounter() {
  _counter = 0;
}

function fgIdFromStep(step: FlowStep): string {
  const raw = (step as Record<string, unknown>)._fgId;
  return typeof raw === 'string' && raw.length > 0 ? raw : newId();
}

// ─── steps → FlowDocumentJSON ─────────────────────────────────────────────────

function stepToNode(step: FlowStep): FlowNodeJSON {
  const id = fgIdFromStep(step);

  // Condition (if_element / if_variable / tap_fb_comment_button — control with then/else)
  if (step.type === 'if_element' || step.type === 'if_variable' || step.type === 'tap_fb_comment_button') {
    const thenNodes = stepsToNodes((step as any).then ?? []);
    const elseNodes = stepsToNodes((step as any).else ?? []);
    const isFbTap = step.type === 'tap_fb_comment_button';
    return {
      id,
      type: 'condition',
      data: { step },
      blocks: [
        {
          id: `${id}_then`,
          type: 'block',
          data: { title: isFbTap ? 'Khi bấm được nút Bình luận' : 'Nếu đúng (then)' },
          blocks: thenNodes,
        },
        {
          id: `${id}_else`,
          type: 'block',
          data: { title: isFbTap ? 'Khi không thấy nút Bình luận' : 'Nếu sai (else)' },
          blocks: elseNodes,
        },
      ],
    };
  }

  // Random pick (multiple branches)
  if (step.type === 'random_pick') {
    const branches: FlowNodeJSON[] = ((step as any).branches ?? []).map(
      (branch: { weight?: number; steps: FlowStep[] }, i: number) => ({
        id: `${id}_branch_${i}`,
        type: 'block',
        data: { title: `Nhánh ${i + 1} (${branch.weight ?? 1})` },
        blocks: stepsToNodes(branch.steps ?? []),
      }),
    );
    return {
      id,
      type: 'condition',
      data: { step },
      blocks:
        branches.length >= 2
          ? branches
          : [
              { id: `${id}_b0`, type: 'block', data: { title: 'Nhánh 1' }, blocks: [] },
              { id: `${id}_b1`, type: 'block', data: { title: 'Nhánh 2' }, blocks: [] },
            ],
    };
  }

  // Loop (repeat / repeat_until / loop)
  if (step.type === 'repeat' || step.type === 'repeat_until' || step.type === 'loop') {
    const bodyNodes = stepsToNodes((step as any).steps ?? []);
    return {
      id,
      type: 'loop_node',
      data: { step },
      blocks: [
        {
          id: `${id}_body`,
          type: 'block',
          data: { title: 'Thân vòng lặp' },
          blocks: bodyNodes,
        },
      ],
    };
  }

  // Default: action node
  return {
    id,
    type: step.type === 'run_scenario' ? 'sub_scenario' : 'action',
    data: { step },
  };
}

function stepsToNodes(steps: FlowStep[]): FlowNodeJSON[] {
  return steps.map((s) => stepToNode(s));
}

export function stepsToFlowDoc(steps: FlowStep[]): FlowDocumentJSON {
  resetCounter();
  return {
    nodes: [
      { id: 'start_0', type: 'start', data: { title: 'Bắt đầu' }, blocks: [] },
      ...stepsToNodes(steps),
      { id: 'end_0', type: 'end', data: { title: 'Kết thúc' } },
    ],
  };
}

// ─── FlowDocumentJSON → steps ─────────────────────────────────────────────────

function withFgId<S extends FlowStep>(nodeId: string, step: S): S {
  return { ...step, _fgId: nodeId } as S;
}

function nodeToStep(node: FlowNodeJSON): FlowStep | null {
  if (node.type === 'start' || node.type === 'end' || node.type === 'block') return null;

  const step = node.data?.step as FlowStep | undefined;
  if (!step) return null;

  // Reconstruct nested steps from blocks
  if (step.type === 'if_element' || step.type === 'if_variable' || step.type === 'tap_fb_comment_button') {
    const thenBlock = node.blocks?.[0];
    const elseBlock = node.blocks?.[1];
    return withFgId(node.id, {
      ...step,
      then: nodesToSteps(thenBlock?.blocks ?? []),
      else: nodesToSteps(elseBlock?.blocks ?? []),
    } as FlowStep);
  }

  if (step.type === 'random_pick') {
    const branches = (node.blocks ?? []).map((block, i) => ({
      weight: (block.data as { weight?: number })?.weight ?? 1,
      steps: nodesToSteps(block.blocks ?? []),
    }));
    return withFgId(node.id, { ...step, branches } as FlowStep);
  }

  if (step.type === 'repeat' || step.type === 'repeat_until' || step.type === 'loop') {
    const bodyBlock = node.blocks?.[0];
    return withFgId(node.id, {
      ...step,
      steps: nodesToSteps(bodyBlock?.blocks ?? []),
    } as FlowStep);
  }

  return withFgId(node.id, step);
}

function nodesToSteps(nodes: FlowNodeJSON[]): FlowStep[] {
  return nodes.flatMap((n) => {
    const s = nodeToStep(n);
    return s ? [s] : [];
  });
}

export function flowDocToSteps(doc: FlowDocumentJSON): FlowStep[] {
  // Top-level nodes, excluding start/end
  const contentNodes = doc.nodes.filter((n) => n.type !== 'start' && n.type !== 'end');
  return nodesToSteps(contentNodes);
}
