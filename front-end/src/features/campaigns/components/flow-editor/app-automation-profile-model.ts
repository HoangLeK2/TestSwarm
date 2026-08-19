import type { FlowStep } from '../scenario-steps/types';

export type AppAutomationProfile = {
  package?: string;
  semantic_locators?: Record<string, SemanticLocator>;
  popup_watchers?: PopupWatcher[];
  login_recipe?: LoginRecipe;
  form_recipes?: Record<string, FormRecipe>;
  [key: string]: unknown;
};

export type SemanticLocator = {
  candidates?: LocatorCandidate[];
  min_score?: number;
  allow_ambiguous?: boolean;
};

export type LocatorCandidate = {
  by?: string;
  value?: string;
  resource_id_contains?: string;
  text_near?: string[];
  target_class?: string;
  class_name?: string;
  description_contains?: string;
  region?: string;
  allow_coordinate_fallback?: boolean;
};

export type LoginRecipe = {
  detect_logged_in?: { any_text?: string[] };
  fields?: Record<string, LoginField>;
  submit?: LoginSubmit;
  post_submit_actions?: LoginPostSubmitAction[];
  post_submit_fields?: Record<string, LoginField>;
  post_submit?: LoginSubmit;
};

export type LoginField = {
  locator?: string;
  value_from?: string;
  input_method?: string;
  required?: boolean;
};

export type LoginSubmit = {
  tap_text?: string;
  tap_text_any?: string[];
  locator?: string;
};

export type LoginPostSubmitAction = LoginSubmit & {
  when_text_any?: string[];
  timeout_s?: number;
  poll_s?: number;
  wait_after_s?: number;
};

export type LoginSetupRequirement =
  | 'package'
  | 'loggedInSignal'
  | 'username'
  | 'password'
  | 'submit';

export type LoginSetupStatus = {
  ready: boolean;
  configuredFieldCount: number;
  missing: LoginSetupRequirement[];
};

export type FormRecipe = {
  fields?: Record<string, FormField>;
  submit?: LoginSubmit;
  mode?: 'strict' | 'best_effort';
};

export type FormField = {
  locator?: string;
  value_from?: string;
  required?: boolean;
};

export type PopupWatcher = {
  name?: string;
  when?: {
    text?: string;
    text_contains?: string[];
    description_contains?: string[];
    resource_id_contains?: string[];
    class_name?: string;
  };
  action?: {
    tap_text?: string;
    tap_text_any?: string[];
    press_key?: string;
    noop?: boolean;
    allow_unsafe?: boolean;
  };
  max_triggers_per_run?: number;
  cooldown_ms?: number;
  enabled?: boolean;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : {};
}

export function csvToList(value: string): string[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

export function listToCsv(value: unknown): string {
  return Array.isArray(value)
    ? value
        .map((item) => String(item))
        .filter(Boolean)
        .join(', ')
    : '';
}

export function appAutomationProfile(step: FlowStep): AppAutomationProfile {
  const raw = asRecord(step.profile);
  return {
    ...raw,
    package: String(raw.package ?? step.package ?? ''),
    semantic_locators: asRecord(raw.semantic_locators) as Record<
      string,
      SemanticLocator
    >,
    popup_watchers: Array.isArray(raw.popup_watchers)
      ? (raw.popup_watchers as PopupWatcher[])
      : [],
    form_recipes: asRecord(raw.form_recipes) as Record<string, FormRecipe>
  };
}

export function withAppAutomationProfile(
  step: FlowStep,
  profile: AppAutomationProfile
): FlowStep {
  return { ...step, profile };
}

export function locatorNames(profile: AppAutomationProfile): string[] {
  return Object.keys(profile.semantic_locators ?? {}).sort((a, b) =>
    a.localeCompare(b)
  );
}

export function firstCandidate(locator?: SemanticLocator): LocatorCandidate {
  return locator?.candidates?.[0] ?? {};
}

export function patchProfile(
  step: FlowStep,
  patch: Partial<AppAutomationProfile>
): FlowStep {
  return withAppAutomationProfile(step, {
    ...appAutomationProfile(step),
    ...patch
  });
}

export function patchLocator(
  step: FlowStep,
  name: string,
  candidatePatch: Partial<LocatorCandidate>,
  locatorPatch: Partial<SemanticLocator> = {}
): FlowStep {
  const profile = appAutomationProfile(step);
  const locators = { ...(profile.semantic_locators ?? {}) };
  const current = locators[name] ?? { candidates: [{}] };
  const remainingCandidates = current.candidates?.slice(1) ?? [];
  const candidate = {
    ...firstCandidate(current),
    ...candidatePatch
  };
  locators[name] = {
    ...current,
    ...locatorPatch,
    candidates: [candidate, ...remainingCandidates]
  };
  return withAppAutomationProfile(step, {
    ...profile,
    semantic_locators: locators
  });
}

export function addLocator(step: FlowStep): FlowStep {
  const profile = appAutomationProfile(step);
  const locators = { ...(profile.semantic_locators ?? {}) };
  let idx = Object.keys(locators).length + 1;
  let name = `field_${idx}`;
  while (locators[name]) {
    idx += 1;
    name = `field_${idx}`;
  }
  locators[name] = {
    candidates: [{ resource_id_contains: name }]
  };
  return withAppAutomationProfile(step, {
    ...profile,
    semantic_locators: locators
  });
}

export function removeLocator(step: FlowStep, name: string): FlowStep {
  const profile = appAutomationProfile(step);
  const locators = { ...(profile.semantic_locators ?? {}) };
  delete locators[name];
  return withAppAutomationProfile(step, {
    ...profile,
    semantic_locators: locators
  });
}

export function ensureLoginRecipe(profile: AppAutomationProfile): LoginRecipe {
  return {
    detect_logged_in: { any_text: [] },
    fields: {},
    submit: { tap_text_any: ['Login', 'Sign in'] },
    ...(profile.login_recipe ?? {})
  };
}

export function patchLoginRecipe(
  step: FlowStep,
  patch: Partial<LoginRecipe>
): FlowStep {
  const profile = appAutomationProfile(step);
  return withAppAutomationProfile(step, {
    ...profile,
    login_recipe: {
      ...ensureLoginRecipe(profile),
      ...patch
    }
  });
}

export function patchLoginField(
  step: FlowStep,
  fieldName: string,
  patch: Partial<LoginField>
): FlowStep {
  const profile = appAutomationProfile(step);
  const recipe = ensureLoginRecipe(profile);
  const fields = { ...(recipe.fields ?? {}) };
  fields[fieldName] = {
    input_method: 'set_text',
    ...(fields[fieldName] ?? {}),
    ...patch
  };
  return patchLoginRecipe(step, { fields });
}

export function patchPostSubmitLoginField(
  step: FlowStep,
  fieldName: string,
  patch: Partial<LoginField>
): FlowStep {
  const profile = appAutomationProfile(step);
  const recipe = ensureLoginRecipe(profile);
  const fields = { ...(recipe.post_submit_fields ?? {}) };
  fields[fieldName] = {
    input_method: 'set_text',
    required: false,
    ...(fields[fieldName] ?? {}),
    ...patch
  };
  return patchLoginRecipe(step, {
    post_submit_fields: fields,
    post_submit: recipe.post_submit ?? {
      tap_text_any: ['Continue', 'Next', 'Tiếp tục']
    }
  });
}

function hasCandidateSignal(candidate: LocatorCandidate): boolean {
  return Boolean(
    (candidate.by?.trim() && candidate.value?.trim()) ||
      candidate.resource_id_contains?.trim() ||
      candidate.description_contains?.trim() ||
      candidate.text_near?.some((text) => text.trim()) ||
      candidate.class_name?.trim()
  );
}

export function patchLoginTarget(
  step: FlowStep,
  fieldName: 'username' | 'password' | 'auth_code',
  candidatePatch: Partial<LocatorCandidate>
): FlowStep {
  const profile = appAutomationProfile(step);
  const recipe = ensureLoginRecipe(profile);
  const isPostSubmitField = fieldName === 'auth_code';
  const currentField = isPostSubmitField
    ? recipe.post_submit_fields?.[fieldName]
    : recipe.fields?.[fieldName];
  const locatorName = currentField?.locator?.trim() || `login_${fieldName}`;
  const locator = profile.semantic_locators?.[locatorName];
  const normalizedPatch = Object.fromEntries(
    Object.entries(candidatePatch).map(([key, value]) => [
      key,
      typeof value === 'string' && !value.trim() ? undefined : value
    ])
  ) as Partial<LocatorCandidate>;
  const nextCandidate = {
    ...firstCandidate(locator),
    ...normalizedPatch
  };

  if (!hasCandidateSignal(nextCandidate)) {
    const fields = {
      ...((isPostSubmitField ? recipe.post_submit_fields : recipe.fields) ?? {})
    };
    delete fields[fieldName];
    const recipePatch = isPostSubmitField
      ? { ...recipe, post_submit_fields: fields }
      : { ...recipe, fields };
    return withAppAutomationProfile(step, {
      ...profile,
      login_recipe: recipePatch
    });
  }

  const withTarget = patchLocator(step, locatorName, normalizedPatch);
  const patchField = isPostSubmitField
    ? patchPostSubmitLoginField
    : patchLoginField;
  return patchField(withTarget, fieldName, {
    locator: locatorName,
    value_from:
      currentField?.value_from ||
      (fieldName === 'password'
        ? 'account.password'
        : fieldName === 'auth_code'
          ? 'account.totp_code'
          : 'account.username'),
    required: fieldName === 'auth_code' ? false : currentField?.required
  });
}

function hasLocatorSignal(locator?: SemanticLocator): boolean {
  return Boolean(locator?.candidates?.some(hasCandidateSignal));
}

export function getLoginSetupStatus(step: FlowStep): LoginSetupStatus {
  const profile = appAutomationProfile(step);
  const recipe = profile.login_recipe;
  const locators = profile.semantic_locators ?? {};
  const missing: LoginSetupRequirement[] = [];

  if (!profile.package?.trim()) missing.push('package');
  if (!recipe?.detect_logged_in?.any_text?.some((text) => text.trim())) {
    missing.push('loggedInSignal');
  }

  let configuredFieldCount = 0;
  for (const fieldName of ['username', 'password'] as const) {
    const field = recipe?.fields?.[fieldName];
    const configured = Boolean(
      field?.value_from?.trim() &&
        field.locator?.trim() &&
        hasLocatorSignal(locators[field.locator])
    );
    if (configured) configuredFieldCount += 1;
    else missing.push(fieldName);
  }

  const submit = recipe?.submit;
  const hasSubmitText = Boolean(
    submit?.tap_text?.trim() ||
      submit?.tap_text_any?.some((text) => text.trim())
  );
  const hasSubmitLocator = Boolean(
    submit?.locator?.trim() && hasLocatorSignal(locators[submit.locator])
  );
  if (!hasSubmitText && !hasSubmitLocator) missing.push('submit');

  return {
    ready: missing.length === 0,
    configuredFieldCount,
    missing
  };
}

export function ensureFormRecipe(
  profile: AppAutomationProfile,
  recipeName: string
): FormRecipe {
  const recipes = profile.form_recipes ?? {};
  return {
    fields: {},
    mode: 'strict',
    ...(recipes[recipeName] ?? {})
  };
}

export function patchFormRecipe(
  step: FlowStep,
  recipeName: string,
  patch: Partial<FormRecipe>
): FlowStep {
  const profile = appAutomationProfile(step);
  const recipes = { ...(profile.form_recipes ?? {}) };
  recipes[recipeName] = {
    ...ensureFormRecipe(profile, recipeName),
    ...patch
  };
  return withAppAutomationProfile(
    { ...step, recipe: recipeName },
    {
      ...profile,
      form_recipes: recipes
    }
  );
}

export function patchFormField(
  step: FlowStep,
  recipeName: string,
  fieldName: string,
  patch: Partial<FormField>
): FlowStep {
  const profile = appAutomationProfile(step);
  const recipe = ensureFormRecipe(profile, recipeName);
  const fields = { ...(recipe.fields ?? {}) };
  fields[fieldName] = {
    required: true,
    ...(fields[fieldName] ?? {}),
    ...patch
  };
  return patchFormRecipe(step, recipeName, { fields });
}

export function removeFormField(
  step: FlowStep,
  recipeName: string,
  fieldName: string
): FlowStep {
  const profile = appAutomationProfile(step);
  const recipe = ensureFormRecipe(profile, recipeName);
  const fields = { ...(recipe.fields ?? {}) };
  delete fields[fieldName];
  return patchFormRecipe(step, recipeName, { fields });
}

export function patchPopupWatcher(
  step: FlowStep,
  index: number,
  patch: Partial<PopupWatcher>
): FlowStep {
  const profile = appAutomationProfile(step);
  const watchers = [...(profile.popup_watchers ?? [])];
  watchers[index] = {
    name: `watcher_${index + 1}`,
    when: { text_contains: [] },
    action: { tap_text_any: ['Later', 'Not now'] },
    enabled: true,
    max_triggers_per_run: 3,
    cooldown_ms: 2000,
    ...(watchers[index] ?? {}),
    ...patch
  };
  return withAppAutomationProfile(step, {
    ...profile,
    popup_watchers: watchers
  });
}

export function addPopupWatcher(step: FlowStep): FlowStep {
  const profile = appAutomationProfile(step);
  const index = (profile.popup_watchers ?? []).length;
  return patchPopupWatcher(step, index, {});
}

export function removePopupWatcher(step: FlowStep, index: number): FlowStep {
  const profile = appAutomationProfile(step);
  const watchers = [...(profile.popup_watchers ?? [])];
  watchers.splice(index, 1);
  return withAppAutomationProfile(step, {
    ...profile,
    popup_watchers: watchers
  });
}
