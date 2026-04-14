/** Path segment from root step into nested lists (then/else/steps/branches…). */
export type ScenarioStepPathSegment = { listKey: string; childIndex: number };

/** Stable key for inline preview run state (root index + path to the step/block). */
export function encodeScenarioInlineRunKey(
  rootIndex: number,
  path: ScenarioStepPathSegment[],
): string {
  if (!path.length) return String(rootIndex);
  return `${rootIndex}/${path.map((p) => `${p.listKey}:${p.childIndex}`).join('/')}`;
}
