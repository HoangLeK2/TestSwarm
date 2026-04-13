'use client';

/**
 * Context cho nút play / chọn node trên Flowgram canvas.
 * UI Flowgram đang tắt tạm ở parent: `ENABLE_FLOWGRAM_CONTROL_UI` / `ENABLE_FLOWGRAM_SCENARIO_UI`.
 */

import { createContext, useContext, type ReactNode } from 'react';
import type { FlowStep } from '@/features/campaigns/components/scenario-steps/types';

export type FlowgramRunState = 'idle' | 'running' | 'ok' | 'error';

export type FlowgramScenarioWorkbench = {
  deviceSerial: string | null;
  selectedFgId: string | null;
  setSelectedFgId: (id: string | null) => void;
  runStates: Record<string, FlowgramRunState>;
  onRunLeafStep: (fgId: string, step: FlowStep) => void;
};

const FlowgramScenarioContext = createContext<FlowgramScenarioWorkbench | null>(null);

export function FlowgramScenarioProvider({
  value,
  children,
}: {
  value: FlowgramScenarioWorkbench;
  children: ReactNode;
}) {
  return <FlowgramScenarioContext.Provider value={value}>{children}</FlowgramScenarioContext.Provider>;
}

export function useFlowgramScenarioWorkbench(): FlowgramScenarioWorkbench | null {
  return useContext(FlowgramScenarioContext);
}
