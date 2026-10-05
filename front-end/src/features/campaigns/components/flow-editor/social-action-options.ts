type Facets = Record<string, string | string[]> | undefined;

export function getSocialActionOptions(_stepType: string, _facets: Facets) {
  return [] as Array<{ value: string }>;
}

export function defaultSocialAction(_stepType: string, _facets: Facets) {
  return '';
}
