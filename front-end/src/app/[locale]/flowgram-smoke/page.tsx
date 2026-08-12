'use client';

import dynamic from 'next/dynamic';

import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

const FlowgramCanvas = dynamic(
  () =>
    import(
      '@/features/scenario-templates/components/scenario-flow-editor/canvas'
    ).then((module) => module.FlowgramCanvas),
  { ssr: false }
);

const steps: FlowStep[] = [
  {
    id: 'if-smoke',
    type: 'if_element',
    by: 'text',
    value: 'Follow',
    then: [{ id: 'then-wait', type: 'wait', seconds: 1 }],
    else: []
  },
  {
    id: 'loop-smoke',
    type: 'repeat',
    count: 2,
    steps: [{ id: 'loop-wait', type: 'wait', seconds: 1 }]
  },
  {
    id: 'random-smoke',
    type: 'random_pick',
    branches: [
      { weight: 2, steps: [] },
      { weight: 1, steps: [{ id: 'random-wait', type: 'wait', seconds: 1 }] }
    ]
  }
];

export default function FlowgramSmokePage() {
  return (
    <main style={{ width: '100vw', height: '100vh' }}>
      <FlowgramCanvas steps={steps} />
    </main>
  );
}
