'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import {
  socialExtApi,
  type PlatformCapability
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
      platforms.map((p) => ({
        value: p.name,
        label: platformLabel(p.name),
        supported: p.step_types.includes(stepType),
        coverage: p.coverage
      })),
    [platforms]
  );

  /** Platforms whose `extract` can collect `entity`. */
  const optionsForEntity = useCallback(
    (entity: string) =>
      platforms.map((p) => ({
        value: p.name,
        label: platformLabel(p.name),
        supported: p.entities.includes(entity),
        coverage: p.coverage
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
