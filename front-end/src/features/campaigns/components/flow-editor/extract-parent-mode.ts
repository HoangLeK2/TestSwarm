export const DEFAULT_CUSTOM_PARENT_POST_ID_VAR = '_fb_comment_parent_pid';

export function parentPostIdVarForMode(
  mode: string,
  currentValue?: string
): string | undefined {
  if (mode === 'auto') return undefined;
  return currentValue || DEFAULT_CUSTOM_PARENT_POST_ID_VAR;
}
