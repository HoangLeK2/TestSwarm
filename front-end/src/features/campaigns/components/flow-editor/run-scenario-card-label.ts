type RunScenarioLabelStep = {
  type?: unknown;
  scenario_id?: unknown;
  scenario_name?: unknown;
};

type ScenarioLabelOption = {
  id?: unknown;
  scenario_id?: unknown;
  name?: unknown;
  title?: unknown;
};

function optionNameForId(
  scenarioId: string,
  options?: ScenarioLabelOption[]
): string {
  if (!scenarioId || !options) return '';
  const match = options.find((scenario) => {
    const id = String(scenario.id || scenario.scenario_id || '').trim();
    return id === scenarioId;
  });
  return String(match?.name || match?.title || '').trim();
}

export function resolveRunScenarioDisplayRef(
  step: RunScenarioLabelStep,
  options?: {
    campaignScenarios?: ScenarioLabelOption[];
    orgScenarios?: ScenarioLabelOption[];
  }
): string {
  if (step.type !== 'run_scenario') return '';
  const scenarioId = String(step.scenario_id || '').trim();
  const scenarioName = String(step.scenario_name || '').trim();
  const campaignScenarioName = optionNameForId(
    scenarioId,
    options?.campaignScenarios
  );
  const orgScenarioName = optionNameForId(scenarioId, options?.orgScenarios);
  return scenarioName || campaignScenarioName || orgScenarioName || scenarioId;
}

export function resolveRunScenarioCardRef(
  step: RunScenarioLabelStep,
  orgScenarios?: ScenarioLabelOption[]
): string {
  return resolveRunScenarioDisplayRef(step, { orgScenarios });
}
