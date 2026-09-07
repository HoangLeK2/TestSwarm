import type { FlowStep } from '../components/scenario-steps/types';
import { decodeScenarioInlineRunKey } from '../components/flow-editor/inline-run-key';
import {
  stepTreePathKey,
  type StepTreePathSegment
} from './step-tree-intelligence';
import {
  analyzeStepVariableLineage,
  type StepVariableLineageIssue
} from './step-variable-lineage';

export type ScenarioLintSeverity = 'critical' | 'warning';

export type ScenarioLintPreflightResult = {
  issues: StepVariableLineageIssue[];
  criticalIssues: StepVariableLineageIssue[];
  warningIssues: StepVariableLineageIssue[];
  hasCritical: boolean;
};

const CRITICAL_ISSUE_KINDS = new Set<StepVariableLineageIssue['kind']>([
  'missing_verified_target',
  'candidate_lease_without_entity',
  'source_var_without_scan',
  'verified_target_without_profile',
  'comment_flow_missing_step'
]);

export function scenarioLintIssueSeverity(
  issue: StepVariableLineageIssue
): ScenarioLintSeverity {
  return CRITICAL_ISSUE_KINDS.has(issue.kind) ? 'critical' : 'warning';
}

export function scenarioLintSummary(
  issues: StepVariableLineageIssue[],
  options: {
    limit?: number;
    formatIssue?: (issue: StepVariableLineageIssue, index: number) => string;
    moreLabel?: (count: number) => string;
  } = {}
): string {
  const limit = options.limit ?? 3;
  const visible = issues.slice(0, limit);
  const formatIssue =
    options.formatIssue ??
    ((issue: StepVariableLineageIssue) =>
      issue.variable
        ? `${issue.kind}: ${issue.variable}`
        : `${issue.kind}: ${issue.source}`);
  const parts = visible.map((issue, index) => formatIssue(issue, index));
  const hidden = issues.length - visible.length;
  if (hidden > 0) {
    parts.push(options.moreLabel?.(hidden) ?? `+${hidden} more`);
  }
  return parts.join('; ');
}

export function scenarioLintPreflightForSteps(
  steps: FlowStep[],
  initialVariables: string[] = []
): ScenarioLintPreflightResult {
  return buildScenarioLintPreflightResult(
    analyzeStepVariableLineage(steps, initialVariables).issues
  );
}

export function scenarioLintPreflightForInlineRun(
  rootSteps: FlowStep[],
  runKey: string,
  fallbackStep: FlowStep,
  initialVariables: string[] = []
): ScenarioLintPreflightResult {
  const pathKey = stepTreePathKeyForInlineRunKey(runKey);
  const isolatedIssues = scenarioLintPreflightForSteps(
    [fallbackStep],
    initialVariables
  ).issues.map((issue) => ({
    ...issue,
    pathKey: pathKey ?? issue.pathKey
  }));
  if (pathKey) {
    const entry = analyzeStepVariableLineage(
      rootSteps,
      initialVariables
    ).byPathKey.get(pathKey);
    if (entry) {
      return buildScenarioLintPreflightResult(
        mergeScenarioLintIssues(entry.issues, isolatedIssues)
      );
    }
  }
  return buildScenarioLintPreflightResult(isolatedIssues);
}

export function stepTreePathKeyForInlineRunKey(runKey: string): string | null {
  const decoded = decodeScenarioInlineRunKey(runKey);
  if (!decoded) return null;
  const path: StepTreePathSegment[] = [
    { listKey: 'steps', ci: decoded.rootIndex },
    ...decoded.path.map(({ listKey, childIndex }) => ({
      listKey: normalizeInlineRunListKey(listKey),
      ci: childIndex
    }))
  ];
  return stepTreePathKey(path);
}

function normalizeInlineRunListKey(listKey: string): string {
  return listKey.endsWith('.steps')
    ? listKey.slice(0, -'.steps'.length)
    : listKey;
}

function buildScenarioLintPreflightResult(
  issues: StepVariableLineageIssue[]
): ScenarioLintPreflightResult {
  const criticalIssues = issues.filter(
    (issue) => scenarioLintIssueSeverity(issue) === 'critical'
  );
  const warningIssues = issues.filter(
    (issue) => scenarioLintIssueSeverity(issue) === 'warning'
  );
  return {
    issues,
    criticalIssues,
    warningIssues,
    hasCritical: criticalIssues.length > 0
  };
}

function mergeScenarioLintIssues(
  first: StepVariableLineageIssue[],
  second: StepVariableLineageIssue[]
): StepVariableLineageIssue[] {
  const merged: StepVariableLineageIssue[] = [];
  const seen = new Set<string>();
  for (const issue of [...first, ...second]) {
    const key = [
      issue.kind,
      issue.variable,
      issue.source,
      issue.pathKey,
      issue.producerPathKey ?? '',
      issue.producerStepType ?? ''
    ].join('\0');
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(issue);
  }
  return merged;
}
