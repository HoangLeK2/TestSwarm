/**
 * Normalize scenario/campaign variable maps for UI and runtime.
 * Template definitions use `{ type, default, description? }`; runtime uses plain values.
 */
export function normalizeScenarioVariables(
  raw: Record<string, unknown> | null | undefined
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw ?? {})) {
    if (
      value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      'type' in value &&
      'default' in value
    ) {
      out[key] = (value as { default?: unknown }).default;
    } else {
      out[key] = value;
    }
  }
  return out;
}

export function mergeScenarioVariables(
  ...layers: Array<Record<string, unknown> | null | undefined>
): Record<string, unknown> {
  return layers.reduce<Record<string, unknown>>(
    (acc, layer) => ({ ...acc, ...normalizeScenarioVariables(layer) }),
    {}
  );
}

/** Read `variables` from pasted scenario JSON (`scenario` wrapper or flat). */
export function extractVariablesFromScenarioJson(
  parsed: unknown
): Record<string, unknown> {
  if (!parsed || typeof parsed !== 'object') return {};
  const root = parsed as Record<string, unknown>;
  const sc =
    root.scenario &&
    typeof root.scenario === 'object' &&
    !Array.isArray(root.scenario)
      ? (root.scenario as Record<string, unknown>)
      : root;
  const vars = sc.variables;
  if (!vars || typeof vars !== 'object' || Array.isArray(vars)) return {};
  return normalizeScenarioVariables(vars as Record<string, unknown>);
}
