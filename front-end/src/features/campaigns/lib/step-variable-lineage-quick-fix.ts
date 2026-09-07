import {
  createDefaultStep,
  type FlowStep
} from '../components/scenario-steps/types';
import type { StepVariableLineageIssue } from './step-variable-lineage';

export type StepVariableLineageQuickFix =
  | {
      id: string;
      kind: 'patch_step';
      labelKey: string;
      descriptionKey: string;
      patch: Partial<FlowStep>;
    }
  | {
      id: string;
      kind: 'insert_step_before';
      labelKey: string;
      descriptionKey: string;
      step: FlowStep;
    }
  | {
      id: string;
      kind: 'select_producer';
      labelKey: string;
      descriptionKey: string;
      producerPathKey: string;
    }
  | {
      id: string;
      kind: 'guidance';
      labelKey: string;
      descriptionKey: string;
    };

export function stepVariableLineageQuickFixes(
  issue: StepVariableLineageIssue,
  step: FlowStep,
  availableVariables: string[] = []
): StepVariableLineageQuickFix[] {
  const fixes: StepVariableLineageQuickFix[] = [];

  if (issue.producerPathKey) {
    fixes.push({
      id: 'select_producer',
      kind: 'select_producer',
      labelKey: 'quickFix.goToProducer',
      descriptionKey: 'quickFix.goToProducerDescription',
      producerPathKey: issue.producerPathKey
    });
  }

  if (issue.kind === 'missing_verified_target') {
    fixes.push({
      id: 'use_verified_target_guard',
      kind: 'patch_step',
      labelKey: 'quickFix.useVerifiedTargetGuard',
      descriptionKey: 'quickFix.useVerifiedTargetGuardDescription',
      patch: {
        require_verified_target: issue.variable || '_people_target'
      }
    });
  }

  if (issue.kind === 'candidate_lease_without_entity') {
    const entityVariable = pickCandidateEntityVariable(availableVariables);
    if (entityVariable) {
      fixes.push({
        id: 'use_candidate_entity_id',
        kind: 'patch_step',
        labelKey: 'quickFix.useCandidateEntityId',
        descriptionKey: 'quickFix.useCandidateEntityIdDescription',
        patch: {
          candidate_entity_id: `\${${entityVariable}}`
        }
      });
    } else {
      fixes.push({
        id: 'add_candidate_entity_id_guidance',
        kind: 'guidance',
        labelKey: 'quickFix.addCandidateEntityId',
        descriptionKey: 'quickFix.addCandidateEntityIdDescription'
      });
    }
  }

  if (
    issue.kind === 'source_var_without_scan' &&
    step.source_var !== '_post_scan'
  ) {
    fixes.push({
      id: 'use_default_post_scan_source',
      kind: 'patch_step',
      labelKey: 'quickFix.useDefaultPostScanSource',
      descriptionKey: 'quickFix.useDefaultPostScanSourceDescription',
      patch: { source_var: '_post_scan' }
    });
  }

  if (issue.kind === 'comment_flow_missing_step') {
    const requiredStep = commentFlowQuickFixStep(issue.variable);
    if (requiredStep) {
      fixes.push({
        id: `insert_${requiredStep.type}`,
        kind: 'insert_step_before',
        labelKey: 'quickFix.insertRequiredStep',
        descriptionKey: 'quickFix.insertRequiredStepDescription',
        step: requiredStep
      });
    }
  }

  if (issue.kind === 'future_reference') {
    fixes.push({
      id: 'move_producer_before_guidance',
      kind: 'guidance',
      labelKey: 'quickFix.moveProducerBefore',
      descriptionKey: 'quickFix.moveProducerBeforeDescription'
    });
  }

  if (issue.kind === 'unknown_reference') {
    if (issue.variable.trim()) {
      fixes.push({
        id: 'insert_set_variable',
        kind: 'insert_step_before',
        labelKey: 'quickFix.insertSetVariable',
        descriptionKey: 'quickFix.insertSetVariableDescription',
        step: {
          ...createDefaultStep('set_variable'),
          name: issue.variable,
          value: ''
        }
      });
    }
    fixes.push({
      id: 'declare_variable_guidance',
      kind: 'guidance',
      labelKey: 'quickFix.declareVariable',
      descriptionKey: 'quickFix.declareVariableDescription'
    });
  }

  if (issue.kind === 'verified_target_without_profile') {
    if (issue.variable.trim()) {
      fixes.push({
        id: 'insert_profile_target_selector',
        kind: 'insert_step_before',
        labelKey: 'quickFix.insertProfileTargetSelector',
        descriptionKey: 'quickFix.insertProfileTargetSelectorDescription',
        step: {
          ...createDefaultStep('social_select_target'),
          target_type: 'person',
          save_as: issue.variable
        }
      });
    }
    fixes.push({
      id: 'replace_target_source_guidance',
      kind: 'guidance',
      labelKey: 'quickFix.replaceTargetSource',
      descriptionKey: 'quickFix.replaceTargetSourceDescription'
    });
  }

  return dedupeFixes(fixes);
}

function pickCandidateEntityVariable(availableVariables: string[]) {
  const preferred = [
    'TARGET_ENTITY_ID',
    'CANDIDATE_ENTITY_ID',
    '_candidate_entity_id',
    'candidate_entity_id'
  ];
  const normalized = new Set(availableVariables.map((name) => name.trim()));
  return (
    preferred.find((name) => normalized.has(name)) ??
    availableVariables.find((name) => /entity_?id/i.test(name))?.trim() ??
    ''
  );
}

function commentFlowQuickFixStep(stepType: string): FlowStep | null {
  if (
    stepType !== 'social_find_comment_button' &&
    stepType !== 'social_tap_comment_target' &&
    stepType !== 'social_apply_comment_filter'
  ) {
    return null;
  }
  return createDefaultStep(stepType);
}

function dedupeFixes(
  fixes: StepVariableLineageQuickFix[]
): StepVariableLineageQuickFix[] {
  const seen = new Set<string>();
  return fixes.filter((fix) => {
    if (seen.has(fix.id)) return false;
    seen.add(fix.id);
    return true;
  });
}
