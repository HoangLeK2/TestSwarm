import type { ScenarioTemplateOut } from '../services/api';

export function humanizeTechnicalName(name: string) {
  const raw = String(name ?? '').trim();
  if (!raw) return '';
  const spaced = raw
    .replace(/[_\-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return spaced
    .split(' ')
    .map((w) =>
      w.toUpperCase() === w ? w : w.charAt(0).toUpperCase() + w.slice(1)
    )
    .join(' ');
}

export function templateDisplayLabel(
  template: Pick<ScenarioTemplateOut, 'name' | 'display_name'>
) {
  const display = String(template.display_name ?? '').trim();
  if (display) return display;
  return humanizeTechnicalName(template.name) || template.name;
}
