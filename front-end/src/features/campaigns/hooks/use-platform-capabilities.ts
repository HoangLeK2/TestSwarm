'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import {
  socialExtApi,
  type PlatformCapability,
  type PlatformCapabilitySupport
} from '../services/social-ext-api';

const PLATFORM_LABELS: Record<string, string> = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  tiktok: 'TikTok',
  threads: 'Threads',
  linkedin: 'LinkedIn'
};

export function platformLabel(name: string): string {
  return PLATFORM_LABELS[name] ?? name;
}

function capabilityIdsForStep(
  platform: PlatformCapability,
  stepType: string
): string[] {
  return Object.entries(platform.capability_schemas ?? {})
    .filter(([, schema]) => schema.step_types.includes(stepType))
    .map(([id]) => id);
}

function supportForStep(
  platform: PlatformCapability,
  stepType: string
): PlatformCapabilitySupport | undefined {
  for (const capabilityId of capabilityIdsForStep(platform, stepType)) {
    const support = platform.capabilities?.[capabilityId];
    if (support) return support;
  }
  return undefined;
}

function isExecutableSupport(
  platform: PlatformCapability,
  support?: PlatformCapabilitySupport
): boolean {
  if (!support) return false;
  if (support.status && support.status !== 'active') return false;
  return platform.coverage.toLowerCase().includes('active');
}

/**
 * Which platforms exist and what each one can run.
 *
 * The capability matrix is static per deployment, so it is cached for the
 * session — a node editor must not fire a request per opened step.
 */
export function usePlatformCapabilities() {
  const query = useQuery({
    queryKey: ['social-ext', 'platforms'],
    queryFn: socialExtApi.listPlatforms,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000
  });

  const platforms: PlatformCapability[] = useMemo(
    () => query.data ?? [],
    [query.data]
  );

  /** Platforms that implement `stepType`, plus those that do not (for greying out). */
  const optionsForStep = useCallback(
    (stepType: string) =>
      platforms.map((p) => {
        const support = supportForStep(p, stepType);
        return {
          value: p.name,
          label: platformLabel(p.name),
          supported:
            p.step_types.includes(stepType) && isExecutableSupport(p, support),
          coverage: p.coverage,
          capabilityIds: capabilityIdsForStep(p, stepType),
          executionMode: support?.execution_mode,
          facets: support?.facets ?? {},
          genericRecipes: support?.generic_recipes ?? []
        };
      }),
    [platforms]
  );

  /** Platforms whose `extract` can collect `entity`. */
  const optionsForEntity = useCallback(
    (entity: string) =>
      platforms.map((p) => ({
        value: p.name,
        label: platformLabel(p.name),
        supported:
          p.entities.includes(entity) &&
          p.coverage.toLowerCase().includes('active'),
        coverage: p.coverage,
        capabilityIds: [],
        executionMode: undefined,
        facets: {},
        genericRecipes: []
      })),
    [platforms]
  );

  return {
    platforms,
    optionsForStep,
    optionsForEntity,
    isLoading: query.isLoading,
    isError: query.isError
  };
}
