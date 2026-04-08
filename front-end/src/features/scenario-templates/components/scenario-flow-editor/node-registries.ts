import { FlowNodeRegistry } from '@flowgram.ai/fixed-layout-editor';
import { v4 as uuidv4 } from 'uuid';

/**
 * Custom node type registries for scenario flow editor.
 * We map our step categories to flowgram node extension types.
 */
export const scenarioNodeRegistries: FlowNodeRegistry[] = [
  // ── Action step (leaf node) ───────────────────────────────────────────────
  {
    type: 'action',
    extend: 'default',
    meta: { defaultExpanded: true },
    onAdd() {
      return {
        id: `action_${uuidv4().slice(0, 8)}`,
        type: 'action',
        data: { step: { type: 'tap_selector', by: 'text', value: '' } },
      };
    },
  },

  // ── Sub-scenario (run_scenario) ───────────────────────────────────────────
  {
    type: 'sub_scenario',
    extend: 'default',
    meta: { defaultExpanded: true },
    onAdd() {
      return {
        id: `sub_${uuidv4().slice(0, 8)}`,
        type: 'sub_scenario',
        data: { step: { type: 'run_scenario', scenario_name: '' } },
      };
    },
  },

  // ── Condition / branch (if_element, if_variable, random_pick) ────────────
  {
    type: 'condition',
    extend: 'dynamicSplit',
    meta: { defaultExpanded: true },
    onAdd() {
      const id = `cond_${uuidv4().slice(0, 8)}`;
      return {
        id,
        type: 'condition',
        data: { step: { type: 'if_element', by: 'text', value: '', then: [], else: [] } },
        blocks: [
          {
            id: `${id}_then`,
            type: 'block',
            data: { title: 'Nếu đúng (then)' },
            blocks: [],
          },
          {
            id: `${id}_else`,
            type: 'block',
            data: { title: 'Nếu sai (else)' },
            blocks: [],
          },
        ],
      };
    },
  },

  // ── Loop node (repeat / repeat_until / loop) ──────────────────────────────
  {
    type: 'loop_node',
    extend: 'loop',
    meta: { defaultExpanded: true },
    onAdd() {
      const id = `loop_${uuidv4().slice(0, 8)}`;
      return {
        id,
        type: 'loop_node',
        data: { step: { type: 'repeat', count: 3, steps: [] } },
        blocks: [
          {
            id: `${id}_body`,
            type: 'block',
            data: { title: 'Thân vòng lặp' },
            blocks: [],
          },
        ],
      };
    },
  },
];
