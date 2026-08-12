'use client';

/**
 * Context cho nút play / chọn node trên Flowgram canvas.
 * Parent screens gate Flowgram with public env-backed feature switches so the
 * legacy list editor can remain available as a fallback.
 */

import { createContext, useContext, type ReactNode } from 'react';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

export type FlowgramRunState = 'idle' | 'running' | 'ok' | 'error';

export type FlowgramScenarioWorkbench = {
  deviceSerial: string | null;
  setSelectedFgId: (id: string | null) => void;
  runStates: Record<string, FlowgramRunState>;
  onRunLeafStep: (fgId: string, step: FlowStep) => void;
};

const FlowgramScenarioContext = createContext<FlowgramScenarioWorkbench | null>(
  null
);

export function FlowgramScenarioProvider({
  value,
  children
}: {
  value: FlowgramScenarioWorkbench;
  children: ReactNode;
}) {
  return (
    <FlowgramScenarioContext.Provider value={value}>
      {children}
    </FlowgramScenarioContext.Provider>
  );
}

export function useFlowgramScenarioWorkbench(): FlowgramScenarioWorkbench | null {
  return useContext(FlowgramScenarioContext);
}
