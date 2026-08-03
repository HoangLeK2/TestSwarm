'use client';

import { useMemo } from 'react';
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient
} from '@tanstack/react-query';
import { scenarioTemplatesApi } from '@/features/scenario-templates/services/api';
import {
  orgScenarioToLibraryItem,
  templateToLibraryItem,
  type ScenarioLibraryItem
} from '../lib/scenario-library-item';
import { importOrgScenarioFileIntoExisting } from '../lib/import-org-scenario-into-existing';
import { prepareImportScenarioFile } from '../lib/prepare-import-scenario-file';
import {
  orgScenariosApi,
  type OrgScenarioBodyIn,
  type OrgScenarioCloneTemplateIn,
  type OrgScenarioCreate,
  type OrgScenarioUpdate,
  type OrgScenarioValidateIn,
  type PreviewStartRequest
} from '../services/api';

export type { ScenarioLibraryItem };

const KEYS = {
  list: ['org-scenarios'] as const,
  templates: ['scenario-templates'] as const,
  detail: (id: string) => ['org-scenarios', id] as const,
  templateDetail: (id: string) => ['scenario-templates', id] as const,
  body: (id: string) => ['org-scenarios', id, 'body'] as const
};
const CATALOG_STALE_MS = 30_000;

export function useOrgScenarios(query?: {
  include_archived?: boolean;
  tag?: string;
  enabled?: boolean;
}) {
  const { enabled = true, ...params } = query ?? {};
  return useQuery({
    queryKey: [...KEYS.list, params] as const,
    queryFn: () => orgScenariosApi.list(params),
    staleTime: CATALOG_STALE_MS,
    enabled
  });
}

export function useScenarioTemplatesCatalog() {
  return useQuery({
    queryKey: KEYS.templates,
    queryFn: () => scenarioTemplatesApi.list(),
    staleTime: CATALOG_STALE_MS
  });
}

export function useMergedOrgScenarios(query?: {
  include_archived?: boolean;
  tag?: string;
}) {
  const orgQuery = useOrgScenarios(query);
  const templatesQuery = useScenarioTemplatesCatalog();

  const data = useMemo(() => {
    const orgItems = (orgQuery.data ?? []).map(orgScenarioToLibraryItem);
    const templateItems = (templatesQuery.data ?? []).map(
      templateToLibraryItem
    );
    const byId = new Map<string, ScenarioLibraryItem>();
    for (const item of [...orgItems, ...templateItems]) {
      if (!byId.has(item.id)) {
        byId.set(item.id, item);
      }
    }
    return Array.from(byId.values()).sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    );
  }, [orgQuery.data, templatesQuery.data]);

  return {
    data,
    isLoading: orgQuery.isLoading || templatesQuery.isLoading,
    error: orgQuery.error ?? templatesQuery.error,
    isError: orgQuery.isError || templatesQuery.isError
  };
}

export function useOrgScenario(scenarioId: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.detail(scenarioId),
    queryFn: () => orgScenariosApi.get(scenarioId),
    enabled: enabled && !!scenarioId
  });
}

export function useScenarioTemplateDetail(templateId: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.templateDetail(templateId),
    queryFn: () => scenarioTemplatesApi.get(templateId),
    enabled: enabled && !!templateId
  });
}

export function useOrgScenarioBody(scenarioId: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.body(scenarioId),
    queryFn: () => orgScenariosApi.getBody(scenarioId),
    enabled: enabled && !!scenarioId
  });
}

/** Fetch scenario bodies for campaign creation / variable merge. */
export function useOrgScenarioBodies(scenarioIds: string[], enabled = true) {
  return useQueries({
    queries: scenarioIds.map((scenarioId) => ({
      queryKey: KEYS.body(scenarioId),
      queryFn: () => orgScenariosApi.getBody(scenarioId),
      enabled: enabled && !!scenarioId
    }))
  });
}

export function useCreateOrgScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: OrgScenarioCreate) => orgScenariosApi.create(data),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      return created;
    }
  });
}

export function useUpdateOrgScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      scenarioId,
      data
    }: {
      scenarioId: string;
      data: OrgScenarioUpdate;
    }) => orgScenariosApi.update(scenarioId, data),
    onSuccess: (_, { scenarioId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(scenarioId) });
    }
  });
}

export function useArchiveOrgScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scenarioId: string) => orgScenariosApi.archive(scenarioId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.templates });
    }
  });
}

export function useRestoreOrgScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scenarioId: string) => orgScenariosApi.restore(scenarioId),
    onSuccess: (_, scenarioId) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.detail(scenarioId) });
    }
  });
}

export function useSaveOrgScenarioBody() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      scenarioId,
      body,
      force
    }: {
      scenarioId: string;
      body: OrgScenarioBodyIn;
      force?: boolean;
    }) => orgScenariosApi.saveBody(scenarioId, body, force),
    onSuccess: (saved, { scenarioId }) => {
      qc.setQueryData(KEYS.body(scenarioId), saved);
      qc.invalidateQueries({ queryKey: KEYS.detail(scenarioId) });
      qc.invalidateQueries({ queryKey: KEYS.body(scenarioId) });
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useValidateOrgScenario() {
  return useMutation({
    mutationFn: ({
      scenarioId,
      body
    }: {
      scenarioId: string;
      body?: OrgScenarioValidateIn | null;
    }) => orgScenariosApi.validate(scenarioId, body)
  });
}

export function useImportOrgScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      resolve,
      targetScenarioId
    }: {
      file: File;
      resolve?: 'reject' | 'create_stub';
      /** When set, import file content into this scenario instead of keeping a new row. */
      targetScenarioId?: string;
    }) =>
      prepareImportScenarioFile(file).then(({ file: prepared }) => {
        const mode = resolve ?? 'create_stub';
        if (targetScenarioId) {
          return importOrgScenarioFileIntoExisting(
            prepared,
            targetScenarioId,
            mode
          );
        }
        return orgScenariosApi.importFile(prepared, resolve);
      }),
    onSuccess: (_, { targetScenarioId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      if (targetScenarioId) {
        qc.invalidateQueries({ queryKey: KEYS.detail(targetScenarioId) });
        qc.invalidateQueries({ queryKey: KEYS.body(targetScenarioId) });
      }
    }
  });
}

export function useCloneScenarioTemplateToOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      templateId,
      data
    }: {
      templateId: string;
      data: OrgScenarioCloneTemplateIn;
    }) => orgScenariosApi.cloneTemplate(templateId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.templates });
    }
  });
}

/** @deprecated Use useCloneScenarioTemplateToOrg */
export const useCloneOrgScenarioTemplate = useCloneScenarioTemplateToOrg;

export function useExportOrgScenario() {
  return useMutation({
    mutationFn: ({
      scenarioId,
      format,
      version
    }: {
      scenarioId: string;
      format?: 'yaml' | 'json';
      version?: number;
    }) => orgScenariosApi.export(scenarioId, format, version)
  });
}

export function useStartOrgScenarioPreview() {
  return useMutation({
    mutationFn: ({
      scenarioId,
      body
    }: {
      scenarioId: string;
      body: PreviewStartRequest;
    }) => orgScenariosApi.startPreview(scenarioId, body)
  });
}

export function usePreviewExecutions(query?: {
  org?: string;
  user?: string;
  since?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ['preview-executions', query] as const,
    queryFn: () => orgScenariosApi.listPreviews(query),
    enabled: query != null
  });
}
