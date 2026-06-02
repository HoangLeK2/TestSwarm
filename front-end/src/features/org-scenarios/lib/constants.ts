import type { ScenarioLibraryItem } from './scenario-library-item';
import { isSystemTemplateItem } from './scenario-library-item';

/** @deprecated Use isSystemTemplateItem — templates come from scenario_templates table. */
export function isSystemTemplateScenario(
  scenario: { is_system_template?: boolean; source?: ScenarioLibraryItem['source'] }
): boolean {
  if (scenario.source === 'template') return true;
  if (scenario.source === 'org') return false;
  return Boolean(scenario.is_system_template);
}

export { isSystemTemplateItem };
