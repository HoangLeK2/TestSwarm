'use client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  scenarioTemplatesApi,
  type ScenarioTemplateCreate,
  type ScenarioTemplateUpdate
} from '../services/api';

const KEYS = {
  list: ['scenario-templates'] as const,
  detail: (id: string) => ['scenario-templates', id] as const
};
const CATALOG_STALE_MS = 30_000;

export function useScenarioTemplates(
  query?: {
    category?: string;
    tags?: string;
  },
  options?: {
    enabled?: boolean;
  }
) {
  return useQuery({
    queryKey: [...KEYS.list, query] as const,
    queryFn: () => scenarioTemplatesApi.list(query),
    staleTime: CATALOG_STALE_MS,
    enabled: options?.enabled ?? true
  });
}

export function useScenarioTemplate(templateId: string) {
  return useQuery({
    queryKey: KEYS.detail(templateId),
    queryFn: () => scenarioTemplatesApi.get(templateId),
    enabled: !!templateId
  });
}

export function useCreateScenarioTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ScenarioTemplateCreate) =>
      scenarioTemplatesApi.create(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useUpdateScenarioTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      templateId,
      data
    }: {
      templateId: string;
      data: ScenarioTemplateUpdate;
    }) => scenarioTemplatesApi.update(templateId, data),
    onSuccess: (_, { templateId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(templateId) });
    }
  });
}

export function useDeleteScenarioTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) => scenarioTemplatesApi.delete(templateId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}

export function useDuplicateScenarioTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) =>
      scenarioTemplatesApi.duplicate(templateId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list })
  });
}
