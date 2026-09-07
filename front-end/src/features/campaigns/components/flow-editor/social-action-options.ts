export type SocialActionOption = {
  value: string;
};

export type SocialActionFacets = Record<string, string | string[] | undefined>;

const SOCIAL_ACTION_OPTIONS: Record<string, SocialActionOption[]> = {
  content_interaction: [
    { value: 'like' },
    { value: 'comment' },
    { value: 'share' }
  ],
  connection_request: [{ value: 'request' }],
  community_membership: [{ value: 'join' }]
};

function facetList(value: string | string[] | undefined): string[] {
  if (Array.isArray(value))
    return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function getSocialActionOptions(
  type: string,
  facets?: SocialActionFacets
): SocialActionOption[] {
  const fallback = SOCIAL_ACTION_OPTIONS[type] ?? [];
  if (type !== 'content_interaction') return fallback;

  const supportedValues = new Set(facetList(facets?.content_actions));
  if (supportedValues.size === 0) return fallback;
  return fallback.filter((option) => supportedValues.has(option.value));
}

export function defaultSocialAction(
  type: string,
  facets?: SocialActionFacets
): string {
  return getSocialActionOptions(type, facets)[0]?.value ?? '';
}
