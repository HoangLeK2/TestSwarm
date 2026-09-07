import type { ScenarioCapabilityPreflightOut } from '../services/api';

export type ScenarioCapabilityPreflight =
  ScenarioCapabilityPreflightOut['preflight'];

export type ScenarioCapabilitySummaryOptions = {
  limit?: number;
  moreLabel?: (count: number) => string;
};

export function scenarioCapabilityIssueSummary(
  preflight: ScenarioCapabilityPreflight,
  options: ScenarioCapabilitySummaryOptions = {}
): string {
  const { limit = 2, moreLabel = (count) => `+${count} more` } = options;
  const issues = preflight.issues ?? [];
  if (issues.length === 0) return '';

  const head = issues.slice(0, limit).map((issue) => {
    const path = issue.path || `#${issue.index + 1}`;
    const missing = issue.missing.join(', ');
    return `${path} ${issue.step_type}: ${missing}`;
  });
  const remaining = issues.length - head.length;
  return remaining > 0
    ? `${head.join('; ')}; ${moreLabel(remaining)}`
    : head.join('; ');
}

export function scenarioCapabilityWarningSummary(
  preflight: ScenarioCapabilityPreflight,
  options: ScenarioCapabilitySummaryOptions = {}
): string {
  const { limit = 2, moreLabel = (count) => `+${count} more` } = options;
  const warnings = preflight.warnings ?? [];
  if (warnings.length === 0) return '';

  const head = warnings.slice(0, limit).map((warning) => {
    const path = warning.path || `#${warning.index + 1}`;
    const unknown = warning.unknown.join(', ');
    return `${path} ${warning.step_type}: ${unknown}`;
  });
  const remaining = warnings.length - head.length;
  return remaining > 0
    ? `${head.join('; ')}; ${moreLabel(remaining)}`
    : head.join('; ');
}
