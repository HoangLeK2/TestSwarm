import type { ExecutionTaskLogStep } from '../types';

type NestedStepDetail = {
  /** null when no label can be derived — the component picks the wording. */
  label: string | null;
  iteration: number | null;
  message: string | null;
  status: string;
};

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function nestedRows(value: unknown): Record<string, unknown>[] {
  if (value == null) return [];
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      const row = objectValue(item);
      const children = row.step_results ?? row.sub_results;
      return Object.keys(row).length ? [row, ...nestedRows(children)] : [];
    });
  }
  const row = objectValue(value);
  const children = row.step_results ?? row.sub_results;
  return children === undefined ? [] : nestedRows(children);
}

export function executionStepDetail(step: ExecutionTaskLogStep): {
  label: string;
  reference: string | null;
  nested: NestedStepDetail[];
} {
  const config = objectValue(step.effective_config_json);
  const trace = objectValue(step.trace);
  const scenarioName =
    text(trace.scenario_name) ??
    text(config.scenario_name) ??
    text(config.name) ??
    text(config.title);
  const label =
    scenarioName ??
    text(step.step_type) ??
    text(step.step_id) ??
    `#${step.step_index}`;
  const reference = scenarioName
    ? (text(step.step_type) ?? text(step.step_id))
    : text(step.step_id);
  const nested = nestedRows(
    trace.sub_results ??
      trace.step_results ??
      config.sub_results ??
      config.step_results
  ).map((row) => ({
    label:
      text(row.scenario_name) ??
      text(row.step_type) ??
      text(row.type) ??
      text(row.name),
    iteration: typeof row.iteration === 'number' ? row.iteration : null,
    message: text(row.message) ?? text(row.error),
    status:
      text(row.status) ??
      (row.ok === false || row.success === false ? 'failed' : 'completed')
  }));

  return { label, reference, nested };
}
