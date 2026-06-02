import type { OrgScenarioSummaryOut } from '../services/api';
import type { ScenarioTemplateOut } from '@/features/scenario-templates/services/api';
import { templateDisplayLabel } from '@/features/scenario-templates/lib/template-label';

export type ScenarioLibraryItem = {
  id: string;
  name: string;
  description: string;
  kind: string;
  status: string;
  scenario_version: number;
  tags: string[];
  updated_at: string;
  is_runnable: boolean;
  source: 'org' | 'template';
  is_system_template: boolean;
  is_builtin?: boolean;
  category?: string;
  /** Present when source === 'org' */
  orgSummary?: OrgScenarioSummaryOut;
  /** Present when source === 'template' */
  template?: ScenarioTemplateOut;
};

function parseTemplateTags(tags: string | undefined): string[] {
  return String(tags ?? '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function templateKind(template: ScenarioTemplateOut): string {
  const nodes = template.nodes ?? [];
  const edges = template.edges ?? [];
  if (
    (Array.isArray(nodes) && nodes.length > 0) ||
    (Array.isArray(edges) && edges.length > 0)
  ) {
    return 'graph';
  }
  return 'sequence';
}

export function orgScenarioToLibraryItem(
  scenario: OrgScenarioSummaryOut
): ScenarioLibraryItem {
  return {
    id: scenario.id,
    name: scenario.name,
    description: scenario.description ?? '',
    kind: scenario.kind,
    status: scenario.status,
    scenario_version: scenario.scenario_version,
    tags: scenario.tags ?? [],
    updated_at: String(scenario.updated_at),
    is_runnable: scenario.is_runnable,
    source: 'org',
    is_system_template: false,
    orgSummary: scenario
  };
}

export function templateToLibraryItem(
  template: ScenarioTemplateOut
): ScenarioLibraryItem {
  const steps = template.steps ?? [];
  const nodes = template.nodes ?? [];
  return {
    id: template.id,
    name: templateDisplayLabel(template),
    description: template.description ?? '',
    kind: templateKind(template),
    status: 'active',
    scenario_version: 1,
    tags: parseTemplateTags(template.tags),
    updated_at: String(template.updated_at),
    is_runnable:
      (Array.isArray(steps) && steps.length > 0) ||
      (Array.isArray(nodes) && nodes.length > 0),
    source: 'template',
    is_system_template: true,
    is_builtin: template.is_builtin,
    category: template.category,
    template
  };
}

export function isSystemTemplateItem(item: ScenarioLibraryItem): boolean {
  return item.source === 'template';
}
