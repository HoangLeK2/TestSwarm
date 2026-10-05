export const CAPTURE_MODES = ['none', 'failure', 'all'] as const;

export type CaptureMode = (typeof CAPTURE_MODES)[number];

export function readCaptureMode(
  variables: Record<string, unknown>
): CaptureMode {
  const value = variables.capture_mode;
  return CAPTURE_MODES.includes(value as CaptureMode)
    ? (value as CaptureMode)
    : 'failure';
}

export function writeCaptureMode(
  variables: Record<string, unknown>,
  mode: CaptureMode
) {
  return { ...variables, capture_mode: mode };
}

export function campaignVariablesForEditor(variables: Record<string, unknown>) {
  return variables;
}

export function mergeCampaignEditorVariables(
  _variables: Record<string, unknown>,
  next: Record<string, unknown>
) {
  return next;
}
