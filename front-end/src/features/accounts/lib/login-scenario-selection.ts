type TaggedScenario = {
  id: string;
  kind?: string | null;
  tags?: string[] | null;
  is_runnable?: boolean;
  status?: string | null;
  updated_at?: string | null;
};

type ScenarioBody = {
  body_json?: Record<string, any> | null;
};

export type LoginScenarioSource =
  | { kind: 'org'; scenarioId: string; steps: any[] }
  | { kind: 'template'; templateId: string; steps: any[] }
  | null;

const SYSTEM_ACCOUNT_LOGIN_TAG = 'system-account-login';

const normalized = (value: string | null | undefined) =>
  String(value ?? '')
    .trim()
    .toLowerCase();

export function hasScenarioTags(
  tags: string[] | null | undefined,
  required: string[]
) {
  const owned = new Set((tags ?? []).map(normalized).filter(Boolean));
  return required.every((tag) => owned.has(normalized(tag)));
}

export function pickOrgLoginScenario<T extends TaggedScenario>(
  scenarios: T[],
  platform: string
): T | null {
  const platformTag = normalized(platform);
  const candidates = scenarios.filter(
    (scenario) =>
      scenario.is_runnable !== false &&
      normalized(scenario.kind || 'sequence') === 'sequence' &&
      normalized(scenario.status) === 'active' &&
      hasScenarioTags(scenario.tags, [
        'login',
        'account-login',
        'login-override',
        SYSTEM_ACCOUNT_LOGIN_TAG
      ]) &&
      hasScenarioPlatformTag(scenario.tags, platformTag)
  );
  candidates.sort((a, b) => {
    return normalized(b.updated_at).localeCompare(normalized(a.updated_at));
  });
  return candidates[0] ?? null;
}

function hasScenarioPlatformTag(
  tags: string[] | null | undefined,
  platform: string
) {
  const owned = new Set((tags ?? []).map(normalized).filter(Boolean));
  return owned.has(platform) || owned.has(`login-platform:${platform}`);
}

export function accountLoginOrgScenarioTags(
  existingTags: string[] | string | null | undefined,
  platform: string
) {
  const rawTags = Array.isArray(existingTags)
    ? existingTags
    : String(existingTags ?? '')
        .split(',')
        .map((tag) => tag.trim());
  const required = [
    'login',
    platform,
    `login-platform:${platform}`,
    'account-login',
    'login-override',
    SYSTEM_ACCOUNT_LOGIN_TAG
  ];
  const byKey = new Map<string, string>();
  for (const tag of [...rawTags, ...required]) {
    const clean = String(tag ?? '').trim();
    if (!clean) continue;
    const key = normalized(clean);
    if (!byKey.has(key)) byKey.set(key, clean);
  }
  const result: string[] = [];
  byKey.forEach((tag) => result.push(tag));
  return result;
}

export function accountLoginOrgScenarioName(template: {
  name?: string | null;
  display_name?: string | null;
}) {
  const base = String(
    template.display_name || template.name || 'Đăng nhập tài khoản'
  ).trim();
  return `${base} (Account Login)`;
}

export function stepsFromOrgScenarioBody(
  body: ScenarioBody | null | undefined
) {
  const steps = body?.body_json?.steps;
  return Array.isArray(steps) ? steps : [];
}

export function resolveLoginScenarioSource({
  orgScenario,
  orgBody,
  template
}: {
  orgScenario?: TaggedScenario | null;
  orgBody?: ScenarioBody | null;
  template?: { id: string; steps?: any[] | null } | null;
}): LoginScenarioSource {
  if (orgScenario) {
    const orgSteps = stepsFromOrgScenarioBody(orgBody);
    if (orgSteps.length > 0) {
      return {
        kind: 'org',
        scenarioId: orgScenario.id,
        steps: orgSteps
      };
    }
  }
  if (template) {
    return {
      kind: 'template',
      templateId: template.id,
      steps: Array.isArray(template.steps) ? template.steps : []
    };
  }
  return null;
}
