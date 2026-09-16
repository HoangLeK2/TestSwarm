/**
 * Option list for the run_scenario (sub-scenario) picker.
 *
 * Three sources, and which one an option came from decides which field the
 * step gets. The workspace library and campaign rows are addressed by
 * `scenario_id` — that is what the runtime registry and org scenario
 * validation resolve against. Shared templates have no id the runtime knows,
 * so they are addressed by `scenario_name` and only resolve on the legacy
 * campaign path.
 *
 * `source` is a closed set on purpose: it used to carry the template's
 * `category` string, so a template categorised "campaign" would have been
 * routed to the id branch and written a scenario_id no registry contains.
 */

export type RunScenarioCampaignOption = {
  id: string;
  name: string;
  steps?: any[];
};

/** Single merge — required so parent does not drop fields when two updates use the same stale `step` (e.g. template pick). */
export type RunScenarioFieldPatch = Partial<{
  scenario_id: string | undefined;
  scenario_name: string | undefined;
  variables: Record<string, any>;
}>;

export type RunScenarioOptionSource = 'campaign' | 'library' | 'template';

export type RunScenarioOption = {
  id: string;
  name: string;
  source: RunScenarioOptionSource;
  /** Template catalog category — display label only, never routing. */
  category?: string;
  steps?: any[];
  variables?: Record<string, any>;
};

export type RunScenarioLibraryOption = { id: string; name: string };

export type RunScenarioTemplateOption = {
  id: string;
  name: string;
  category?: string;
  steps?: any[];
  variables?: Record<string, any>;
};

export function buildRunScenarioOptions({
  campaignScenarios = [],
  libraryScenarios = [],
  templates = []
}: {
  campaignScenarios?: RunScenarioCampaignOption[];
  libraryScenarios?: RunScenarioLibraryOption[];
  templates?: RunScenarioTemplateOption[];
}): RunScenarioOption[] {
  return [
    ...campaignScenarios.map((s) => ({
      id: s.id,
      name: s.name,
      source: 'campaign' as const,
      steps: s.steps,
      variables: {} as Record<string, any>
    })),
    ...libraryScenarios.map((s) => ({
      id: s.id,
      name: s.name,
      source: 'library' as const,
      variables: {} as Record<string, any>
    })),
    ...templates.map((t) => ({
      id: t.id,
      name: t.name,
      source: 'template' as const,
      category: t.category,
      steps: t.steps,
      variables: t.variables
    }))
  ];
}

/**
 * Match by id first: a library scenario and a template may share a name.
 *
 * Takes the two refs rather than the step — `FlowStep` is a union and most of
 * its members carry neither field.
 */
export function findSelectedRunScenario(
  options: RunScenarioOption[],
  ref: { scenarioId?: string | null; scenarioName?: string | null }
): RunScenarioOption | undefined {
  return (
    (ref.scenarioId
      ? options.find((o) => o.id === ref.scenarioId)
      : undefined) ??
    (ref.scenarioName
      ? options.find((o) => o.name === ref.scenarioName)
      : undefined)
  );
}

export function runScenarioPatchFor(
  option: RunScenarioOption
): RunScenarioFieldPatch {
  return option.source === 'template'
    ? { scenario_name: option.name, scenario_id: undefined }
    : { scenario_id: option.id, scenario_name: undefined };
}
