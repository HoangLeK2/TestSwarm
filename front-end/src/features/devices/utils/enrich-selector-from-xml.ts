/**
 * Build nested selector.spec with conditions + instance from a hierarchy XML node.
 * Used by record / pick-from-screen so users never need to type JSON manually.
 */

import type { ScenarioSelectorShape } from '../lib/scenario-selector-step';

const CONTAINER_CLASSES = new Set([
  'android.widget.FrameLayout',
  'android.widget.LinearLayout',
  'android.widget.RelativeLayout',
  'android.view.View',
  'android.view.ViewGroup',
  'androidx.constraintlayout.widget.ConstraintLayout',
  'android.widget.ScrollView',
  'androidx.recyclerview.widget.RecyclerView'
]);

type PrimaryBy =
  | 'resource-id'
  | 'text'
  | 'description'
  | 'xpath'
  | 'class name';

function isSystemPackage(pkg: string): boolean {
  return !pkg || pkg === 'android' || pkg.startsWith('com.android.systemui');
}

function primaryMatches(node: Element, by: PrimaryBy, value: string): boolean {
  switch (by) {
    case 'resource-id':
      return (node.getAttribute('resource-id') ?? '').trim() === value;
    case 'text':
      return (node.getAttribute('text') ?? '').trim() === value;
    case 'description':
      return (node.getAttribute('content-desc') ?? '').trim() === value;
    case 'class name':
      return (node.getAttribute('class') ?? '').trim() === value;
    default:
      return false;
  }
}

function conditionsMatch(
  node: Element,
  conditions: Record<string, unknown>
): boolean {
  for (const [key, expected] of Object.entries(conditions)) {
    if (expected == null) continue;
    if (key === 'className') {
      if ((node.getAttribute('class') ?? '') !== String(expected)) return false;
      continue;
    }
    if (key === 'clickable') {
      const want = expected === true;
      const has = node.getAttribute('clickable') === 'true';
      if (want !== has) return false;
      continue;
    }
    if (key === 'packageName') {
      if ((node.getAttribute('package') ?? '') !== String(expected))
        return false;
      continue;
    }
    if (key === 'resourceId') {
      if ((node.getAttribute('resource-id') ?? '') !== String(expected))
        return false;
      continue;
    }
    if (key === 'enabled') {
      const has = node.getAttribute('enabled') !== 'false';
      if (Boolean(expected) !== has) return false;
      continue;
    }
  }
  return true;
}

function buildConditions(
  node: Element,
  primary: { by: PrimaryBy; value: string }
): Record<string, unknown> {
  const cls = (node.getAttribute('class') ?? '').trim();
  const pkg = (node.getAttribute('package') ?? '').trim();
  const rid = (node.getAttribute('resource-id') ?? '').trim();
  const clickable = node.getAttribute('clickable') === 'true';
  const conditions: Record<string, unknown> = {};

  if (cls && !CONTAINER_CLASSES.has(cls)) {
    conditions.className = cls;
  }
  if (clickable) {
    conditions.clickable = true;
  }
  if (pkg && !isSystemPackage(pkg)) {
    conditions.packageName = pkg;
  }
  // When primary is text/desc, pin resource-id if present (often unique within screen region)
  if (primary.by !== 'resource-id' && rid && rid.includes('/')) {
    conditions.resourceId = rid;
  }
  if (primary.by === 'resource-id' && cls && !CONTAINER_CLASSES.has(cls)) {
    // className already set
  }

  return conditions;
}

/**
 * Turn a primary by/value + chosen DOM node into a full ScenarioSelectorShape.
 */
export function enrichSelectorFromNode(
  node: Element,
  primary: { by: PrimaryBy; value: string },
  allNodes: Element[]
): ScenarioSelectorShape {
  if (primary.by === 'xpath') {
    return { by: 'xpath', value: primary.value };
  }

  const conditions = buildConditions(node, primary);
  let matches = allNodes.filter(
    (n) =>
      primaryMatches(n, primary.by, primary.value) &&
      conditionsMatch(n, conditions)
  );

  // Relax package if over-filtered (e.g. transient overlay)
  if (matches.length === 0 && conditions.packageName) {
    const { packageName: _pkg, ...rest } = conditions;
    const relaxed = { ...rest };
    matches = allNodes.filter(
      (n) =>
        primaryMatches(n, primary.by, primary.value) &&
        conditionsMatch(n, relaxed)
    );
    if (matches.length > 0) {
      delete conditions.packageName;
    }
  }

  // Drop resourceId from conditions if it eliminates all matches
  if (matches.length === 0 && conditions.resourceId) {
    const { resourceId: _rid, ...rest } = conditions;
    matches = allNodes.filter(
      (n) =>
        primaryMatches(n, primary.by, primary.value) && conditionsMatch(n, rest)
    );
    if (matches.length > 0) {
      delete conditions.resourceId;
    }
  }

  let instance: number | undefined;
  if (matches.length > 1) {
    const idx = matches.indexOf(node);
    if (idx >= 0) instance = idx;
  }

  const spec: ScenarioSelectorShape = {
    by: primary.by as ScenarioSelectorShape['by'],
    value: primary.value
  };
  if (Object.keys(conditions).length > 0) {
    spec.conditions = conditions;
  }
  if (instance != null) {
    spec.instance = instance;
  }
  return spec;
}
