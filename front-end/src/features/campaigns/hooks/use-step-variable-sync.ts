'use client';

import { useRef } from 'react';
import {
  syncScenarioVariablesWithStepReferences,
  type ScenarioVariableReferenceSync
} from '@/lib/scenario-variable-references';
import { analyzeStepVariableLineage } from '../lib/step-variable-lineage';
import type { FlowStep } from '../components/scenario-steps/types';

export function useStepVariableSync() {
  const managedNamesRef = useRef<Set<string>>(new Set());
  const apiRef = useRef<{
    reset: () => void;
    sync: (
      previousSteps: FlowStep[],
      nextSteps: FlowStep[],
      variables: Record<string, unknown>
    ) => ScenarioVariableReferenceSync;
  } | null>(null);

  if (!apiRef.current) {
    apiRef.current = {
      reset: () => {
        managedNamesRef.current = new Set();
      },
      sync: (
        previousSteps: FlowStep[],
        nextSteps: FlowStep[],
        variables: Record<string, unknown>
      ): ScenarioVariableReferenceSync => {
        const producedNames = new Set(
          analyzeStepVariableLineage(nextSteps).allProduced
        );
        const result = syncScenarioVariablesWithStepReferences(
          previousSteps,
          nextSteps,
          variables,
          managedNamesRef.current,
          producedNames
        );
        managedNamesRef.current = result.managedNames;
        return result;
      }
    };
  }

  return apiRef.current;
}
