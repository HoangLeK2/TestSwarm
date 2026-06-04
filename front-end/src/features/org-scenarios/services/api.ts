import { farmApi } from '@/lib/farm-api';
import type {
  OrgScenarioBodyIn,
  OrgScenarioBodyOut,
  OrgScenarioCloneTemplateIn,
  OrgScenarioCreate,
  OrgScenarioImportOut,
  OrgScenarioOut,
  OrgScenarioSummaryOut,
  OrgScenarioUpdate,
  OrgScenarioValidateIn,
  OrgScenarioValidationOut,
  PreviewListResponse,
  PreviewStartRequest,
  PreviewStartResponse
} from '../../device-farm/services/generated/DeviceFarmApi';

export type {
  OrgScenarioBodyIn,
  OrgScenarioBodyOut,
  OrgScenarioCloneTemplateIn,
  OrgScenarioCreate,
  OrgScenarioImportOut,
  OrgScenarioOut,
  OrgScenarioSummaryOut,
  OrgScenarioUpdate,
  OrgScenarioValidateIn,
  OrgScenarioValidationOut,
  PreviewListResponse,
  PreviewStartRequest,
  PreviewStartResponse
};

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export const orgScenariosApi = {
  list: (query?: { include_archived?: boolean; tag?: string; org?: string }) =>
    farmApi
      .get<OrgScenarioSummaryOut[]>('/scenarios', { params: query })
      .then((r) => r.data),

  listTemplates: () =>
    farmApi
      .get<OrgScenarioSummaryOut[]>('/scenarios/templates')
      .then((r) => r.data),

  get: (scenarioId: string) =>
    farmApi.get<OrgScenarioOut>(`/scenarios/${scenarioId}`).then((r) => r.data),

  create: (data: OrgScenarioCreate) =>
    farmApi.post<OrgScenarioOut>('/scenarios', data).then((r) => r.data),

  update: (scenarioId: string, data: OrgScenarioUpdate) =>
    farmApi
      .patch<OrgScenarioOut>(`/scenarios/${scenarioId}`, data)
      .then((r) => r.data),

  archive: (scenarioId: string) =>
    farmApi
      .delete<OrgScenarioOut>(`/scenarios/${scenarioId}`)
      .then((r) => r.data),

  restore: (scenarioId: string) =>
    farmApi
      .post<OrgScenarioOut>(`/scenarios/${scenarioId}/restore`)
      .then((r) => r.data),

  getBody: (scenarioId: string) =>
    farmApi
      .get<OrgScenarioBodyOut>(`/scenarios/${scenarioId}/body`)
      .then((r) => r.data),

  saveBody: (scenarioId: string, data: OrgScenarioBodyIn, force = false) =>
    farmApi
      .post<OrgScenarioBodyOut>(`/scenarios/${scenarioId}/body`, data, {
        params: force ? { force: true } : undefined
      })
      .then((r) => r.data),

  validate: (scenarioId: string, data?: OrgScenarioValidateIn | null) =>
    farmApi
      .post<OrgScenarioValidationOut>(
        `/scenarios/${scenarioId}/validate`,
        data ?? {}
      )
      .then((r) => r.data),

  importFile: (file: File, resolve: 'reject' | 'create_stub' = 'reject') => {
    const form = new FormData();
    form.append('file', file);
    return farmApi
      .post<OrgScenarioImportOut>('/scenarios/import', form, {
        params: { resolve },
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      .then((r) => r.data);
  },

  cloneTemplate: (templateId: string, data: OrgScenarioCloneTemplateIn) =>
    farmApi
      .post<OrgScenarioImportOut>(
        `/scenarios/templates/${templateId}/clone`,
        data
      )
      .then((r) => r.data),

  export: async (
    scenarioId: string,
    format: 'yaml' | 'json' = 'yaml',
    version?: number
  ) => {
    const response = await farmApi.get<Blob>(
      `/scenarios/${scenarioId}/export`,
      {
        params: { format, ...(version != null ? { version } : {}) },
        responseType: 'blob'
      }
    );
    const disposition = String(response.headers['content-disposition'] ?? '');
    const match = /filename="([^"]+)"/.exec(disposition);
    const filename =
      match?.[1] ??
      `scenario-${scenarioId}.${format === 'yaml' ? 'yaml' : 'json'}`;
    triggerBlobDownload(response.data, filename);
  },

  startPreview: (scenarioId: string, data: PreviewStartRequest) =>
    farmApi
      .post<PreviewStartResponse>(`/scenarios/${scenarioId}/preview`, data)
      .then((r) => r.data),

  listPreviews: (query?: {
    org?: string;
    user?: string;
    since?: string;
    limit?: number;
    offset?: number;
  }) =>
    farmApi
      .get<PreviewListResponse>('/preview', { params: query })
      .then((r) => r.data)
};
