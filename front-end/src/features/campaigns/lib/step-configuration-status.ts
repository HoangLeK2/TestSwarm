import {
  isContainerType,
  type FlowStep
} from '../components/scenario-steps/types';
import { analyzeStepTree, stepTreePathKey } from './step-tree-intelligence';

export type StepConfigurationState = 'complete' | 'warning' | 'missing';
export type StepConfigurationIssueSeverity = 'warning' | 'missing';

export type StepConfigurationIssue = {
  code: string;
  severity: StepConfigurationIssueSeverity;
  labelKey: StepConfigurationIssueLabelKey;
  values?: Record<string, string | number>;
};

export type StepConfigurationStatus = {
  state: StepConfigurationState;
  issues: StepConfigurationIssue[];
  missingFields: StepConfigurationIssue[];
  warnings: StepConfigurationIssue[];
};

export type StepConfigurationTreeStatus = {
  step: FlowStep;
  pathKey: string;
  status: StepConfigurationStatus;
};

export type StepConfigurationIssueLabelKey =
  | 'appProfile'
  | 'assertionCriteria'
  | 'childSteps'
  | 'command'
  | 'comparisonValue'
  | 'condition'
  | 'imageTemplate'
  | 'localPath'
  | 'packageName'
  | 'randomBranch'
  | 'recipe'
  | 'remotePath'
  | 'scenarioReference'
  | 'screenshot'
  | 'selector'
  | 'targetConstraints'
  | 'text'
  | 'url'
  | 'variableKey'
  | 'variableName';

type MutableIssueList = StepConfigurationIssue[];

function hasText(value: unknown): boolean {
  if (typeof value === 'string') return value.trim().length > 0;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'boolean') return true;
  if (Array.isArray(value)) return value.length > 0;
  return value != null;
}

function hasNonEmptyArray(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0;
}

function selectorValue(step: FlowStep): unknown {
  const record = step as { selector?: { value?: unknown }; value?: unknown };
  return record.value ?? record.selector?.value;
}

function addMissing(
  issues: MutableIssueList,
  code: string,
  labelKey: StepConfigurationIssueLabelKey,
  values?: Record<string, string | number>
) {
  issues.push({ code, severity: 'missing', labelKey, values });
}

function addWarning(
  issues: MutableIssueList,
  code: string,
  labelKey: StepConfigurationIssueLabelKey,
  values?: Record<string, string | number>
) {
  issues.push({ code, severity: 'warning', labelKey, values });
}

function requireText(
  issues: MutableIssueList,
  step: FlowStep,
  field: string,
  labelKey: StepConfigurationIssueLabelKey
) {
  if (!hasText((step as Record<string, unknown>)[field])) {
    addMissing(issues, `${step.type}.${field}`, labelKey);
  }
}

function requireSelector(issues: MutableIssueList, step: FlowStep) {
  if (!hasText(selectorValue(step))) {
    addMissing(issues, `${step.type}.selector`, 'selector');
  }
}

function comparatorConfigured(step: FlowStep): boolean {
  return [
    step.equals,
    step.not_equals,
    step.contains,
    step.greater_than,
    step.less_than,
    step.matches
  ].some(hasText);
}

function conditionConfigured(condition: unknown): boolean {
  if (!condition || typeof condition !== 'object') return false;
  const record = condition as Record<string, unknown>;
  const elementCondition = record.element_exists ?? record.element_not_exists;
  if (elementCondition && typeof elementCondition === 'object') {
    return hasText((elementCondition as { value?: unknown }).value);
  }
  const variableCondition = record.variable_equals;
  if (variableCondition && typeof variableCondition === 'object') {
    const data = variableCondition as { name?: unknown; value?: unknown };
    return hasText(data.name) && hasText(data.value);
  }
  return Object.values(record).some((value) => {
    if (value && typeof value === 'object') return conditionConfigured(value);
    return hasText(value);
  });
}

function childCount(step: FlowStep, field: 'steps' | 'then' | 'else'): number {
  const value = (step as Record<string, unknown>)[field];
  return Array.isArray(value) ? value.length : 0;
}

function warnWhenContainerEmpty(issues: MutableIssueList, step: FlowStep) {
  if (!isContainerType(step.type)) return;
  if (
    (step.type === 'loop' ||
      step.type === 'repeat' ||
      step.type === 'repeat_until') &&
    childCount(step, 'steps') === 0
  ) {
    addWarning(issues, `${step.type}.steps.empty`, 'childSteps');
  }
  if (
    (step.type === 'if' ||
      step.type === 'if_element' ||
      step.type === 'if_variable' ||
      step.type === 'social_open_comments') &&
    childCount(step, 'then') === 0 &&
    childCount(step, 'else') === 0
  ) {
    addWarning(issues, `${step.type}.branches.empty`, 'childSteps');
  }
  if (step.type === 'random_pick') {
    const branches = (step as { branches?: Array<{ steps?: FlowStep[] }> })
      .branches;
    if (!Array.isArray(branches) || branches.length === 0) {
      addMissing(issues, 'random_pick.branches', 'randomBranch');
      return;
    }
    branches.forEach((branch, index) => {
      if (!Array.isArray(branch.steps) || branch.steps.length === 0) {
        addWarning(issues, 'random_pick.branch.empty', 'randomBranch', {
          number: index + 1
        });
      }
    });
  }
}

function analyzeActionStep(step: FlowStep, issues: MutableIssueList) {
  switch (step.type) {
    case 'launch_app':
    case 'stop_app':
    case 'clear_app':
    case 'wait_app':
      requireText(issues, step, 'package', 'packageName');
      break;
    case 'push_file':
      requireText(issues, step, 'local_path', 'localPath');
      requireText(issues, step, 'remote_path', 'remotePath');
      break;
    case 'pull_file':
      requireText(issues, step, 'remote_path', 'remotePath');
      requireText(issues, step, 'local_path', 'localPath');
      break;
    case 'open_url':
    case 'install_apk':
      requireText(issues, step, 'url', 'url');
      break;
    case 'tap_selector':
    case 'wait_element':
    case 'assert_element':
    case 'long_tap_selector':
    case 'scroll_to':
      requireSelector(issues, step);
      break;
    case 'tap_xml_match':
      if (![step.contains, step.equals, step.text].some(hasText)) {
        addMissing(issues, 'tap_xml_match.match', 'selector');
      }
      break;
    case 'tap_image':
      requireText(issues, step, 'template_key', 'imageTemplate');
      break;
    case 'input_text':
    case 'set_clipboard':
      requireText(issues, step, 'text', 'text');
      break;
    case 'input_selector':
      requireSelector(issues, step);
      requireText(issues, step, 'text', 'text');
      break;
    case 'adb_shell':
      if (![step.command, step.cmd].some(hasText)) {
        addMissing(issues, 'adb_shell.command', 'command');
      }
      break;
    case 'verify_screen':
      if (![step.template_key, step.screenshot].some(hasText)) {
        addMissing(issues, 'verify_screen.template_key', 'imageTemplate');
      }
      break;
    case 'login_if_needed':
      if (!hasText(step.profile?.package)) {
        addMissing(issues, 'login_if_needed.profile.package', 'appProfile');
      }
      break;
    case 'fill_form':
      if (!hasText(step.profile?.package)) {
        addMissing(issues, 'fill_form.profile.package', 'appProfile');
      }
      requireText(issues, step, 'recipe', 'recipe');
      break;
    case 'assert_app_state':
      if (
        !hasNonEmptyArray(step.any_text) &&
        !hasNonEmptyArray(step.all_text) &&
        !hasNonEmptyArray(step.not_text) &&
        !hasText(step.locator)
      ) {
        addMissing(issues, 'assert_app_state.criteria', 'assertionCriteria');
      }
      break;
    case 'set_variable':
      requireText(issues, step, 'name', 'variableName');
      break;
    case 'set_var':
      requireText(issues, step, 'key', 'variableKey');
      break;
    case 'social_scan_posts_interact':
      if (step.require_comment !== false && !hasText(step.comment_text)) {
        addMissing(issues, 'social_scan_posts_interact.comment_text', 'text');
      }
      break;
    case 'content_interaction':
      if (step.action === 'comment' && !hasText(step.comment_text)) {
        addMissing(issues, 'content_interaction.comment_text', 'text');
      }
      break;
    case 'social_select_target':
      if (
        !hasText(step.search) &&
        !hasText(step.display_name) &&
        !hasText(step.display_text) &&
        !hasNonEmptyArray(step.required_keywords) &&
        !hasNonEmptyArray(step.optional_keywords)
      ) {
        addWarning(
          issues,
          'social_select_target.constraints',
          'targetConstraints'
        );
      }
      break;
  }
}

function analyzeControlStep(step: FlowStep, issues: MutableIssueList) {
  switch (step.type) {
    case 'repeat':
      if (!hasText(step.count) || Number(step.count) < 1) {
        addMissing(issues, 'repeat.count', 'condition');
      }
      break;
    case 'loop':
      if (!hasText(step.count)) {
        addMissing(issues, 'loop.count', 'condition');
      }
      break;
    case 'repeat_until':
      if (!conditionConfigured(step.condition)) {
        addMissing(issues, 'repeat_until.condition', 'condition');
      }
      break;
    case 'if':
    case 'break_if':
      if (!conditionConfigured(step.condition)) {
        addMissing(issues, `${step.type}.condition`, 'condition');
      }
      break;
    case 'if_element':
      requireSelector(issues, step);
      break;
    case 'if_variable':
      requireText(issues, step, 'name', 'variableName');
      if (!comparatorConfigured(step)) {
        addMissing(issues, 'if_variable.comparator', 'comparisonValue');
      }
      break;
    case 'run_scenario':
      if (![step.scenario_name, step.scenario_id].some(hasText)) {
        addMissing(issues, 'run_scenario.reference', 'scenarioReference');
      }
      break;
  }
}

export function analyzeStepConfiguration(
  step: FlowStep
): StepConfigurationStatus {
  const issues: StepConfigurationIssue[] = [];
  analyzeActionStep(step, issues);
  analyzeControlStep(step, issues);
  warnWhenContainerEmpty(issues, step);

  const missingFields = issues.filter((issue) => issue.severity === 'missing');
  const warnings = issues.filter((issue) => issue.severity === 'warning');
  const state =
    missingFields.length > 0
      ? 'missing'
      : warnings.length > 0
        ? 'warning'
        : 'complete';

  return { state, issues, missingFields, warnings };
}

export function analyzeStepConfigurationTree(
  steps: FlowStep[]
): StepConfigurationTreeStatus[] {
  return analyzeStepTree(steps).map((node) => ({
    step: node.step,
    pathKey: stepTreePathKey(node.path),
    status: analyzeStepConfiguration(node.step)
  }));
}
