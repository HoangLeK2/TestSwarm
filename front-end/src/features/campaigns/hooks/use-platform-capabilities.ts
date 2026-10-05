type PlatformOption = {
  value: string;
  label: string;
  supported: boolean;
  coverage: string;
  capabilityIds: string[];
  facets: Record<string, string | string[]>;
  genericRecipes: string[];
};

export function usePlatformCapabilities() {
  const optionsForStep = (_stepType: string): PlatformOption[] => [];
  const optionsForEntity = (_entity: string): PlatformOption[] => [];
  return { optionsForStep, optionsForEntity, isLoading: false, isError: false };
}
