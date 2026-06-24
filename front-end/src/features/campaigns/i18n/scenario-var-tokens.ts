/** Literal `${…}` examples for next-intl placeholders (ICU cannot escape `$` + `{`). */
export const SCENARIO_VAR_TOKENS = {
  VAR: '${VAR}',
  SCROLL_X_RATIO: '${SCROLL_X_RATIO}',
  SAVE_COLLECTION: '${SAVE_COLLECTION}',
  GROUP_NAME: '${GROUP_NAME}',
  BUILTIN: '${__BUILTIN__}'
} as const;
