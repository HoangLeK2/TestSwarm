type RunScenarioLabelStep = {
  type?: unknown;
  scenario_id?: unknown;
  scenario_name?: unknown;
};

type OrgScenarioLabelOption = {
  id?: unknown;
  name?: unknown;
};

export function resolveRunScenarioCardRef(
  step: RunScenarioLabelStep,
  orgScenarios?: OrgScenarioLabelOption[]
): string {
  if (step.type !== 'run_scenario') return '';
  const scenarioId = String(step.scenario_id || '').trim();
  const scenarioName = String(step.scenario_name || '').trim();
  const orgScenarioName =
    scenarioId && orgScenarios
      ? String(
          orgScenarios.find((scenario) => scenario.id === scenarioId)?.name ||
            ''
        ).trim()
      : '';
  return scenarioName || orgScenarioName || scenarioId;
}
