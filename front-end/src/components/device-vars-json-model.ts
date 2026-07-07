const VARIABLE_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

function flattenVarValue(value: unknown): unknown {
  if (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    'type' in value &&
    'default' in value
  ) {
    return (value as { default?: unknown }).default;
  }
  return value;
}

export function flattenCampaignDeviceVariableDefinitions(
  raw?: Record<string, unknown> | null
) {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw ?? {})) {
    if (!VARIABLE_KEY_RE.test(key) || key.startsWith('__')) continue;
    out[key] = flattenVarValue(value);
  }
  return out;
}

/** Resolve globals for device vars: scenario values are defaults, campaign values win per campaign. */
export function mergeCampaignScenarioVariables(
  campaignVariables?: Record<string, unknown> | null,
  scenarioVariables?: Record<string, unknown> | null
) {
  return {
    ...flattenCampaignDeviceVariableDefinitions(scenarioVariables ?? undefined),
    ...flattenCampaignDeviceVariableDefinitions(campaignVariables ?? undefined)
  };
}
