import {
  filenameFromContentDisposition,
  triggerBlobDownload
} from '@/features/content/lib/download';
import { farmApi } from '@/lib/farm-api';
import { blobFromExportResponse } from '@/lib/parse-export-blob';
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
        timeout: 120_000
      })
      .then((r) => r.data);
  },

  importFileIntoExisting: (
    scenarioId: string,
    file: File,
    resolve: 'reject' | 'create_stub' = 'reject'
  ) => {
    const form = new FormData();
    form.append('file', file);
    return farmApi
      .post<OrgScenarioImportOut>(
        `/scenarios/${scenarioId}/import-body`,
        form,
        {
          params: { resolve },
          timeout: 120_000
        }
      )
      .then((r) => r.data);
  },

  cloneTemplate: (templateId: string, data: OrgScenarioCloneTemplateIn) =>
    farmApi
      .post<OrgScenarioImportOut>(
        `/scenarios/templates/${templateId}/clone`,
        data
      )
      .then((r) => r.data),

  ensureAccountLogin: (data: { platform: string }) =>
    farmApi
      .post<OrgScenarioOut>('/scenarios/account-login/effective', data)
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
    const blob = await blobFromExportResponse(response, format);
    const disposition = String(response.headers['content-disposition'] ?? '');
    const filename =
      filenameFromContentDisposition(disposition) ??
      `scenario-${scenarioId}.${format === 'yaml' ? 'yaml' : 'json'}`;
    triggerBlobDownload(blob, filename);
    return { size: blob.size, filename };
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
      .then((r) => r.data),

  /**
   * Store a cropped screen region for a tap_image step.
   *
   * `warning` comes back non-empty when the crop is too featureless to identify
   * one spot — a flat region matches everywhere at full confidence, so the step
   * would tap the wrong place and still report success. Surface it at crop time.
   */
  uploadImageTemplate: async (
    scenarioId: string,
    blob: Blob,
    screen?: { w?: number; h?: number }
  ): Promise<ImageTemplateUploadOut> => {
    const form = new FormData();
    form.append('file', blob, 'template.png');
    const r = await farmApi.post<ImageTemplateUploadOut>(
      `/scenarios/${scenarioId}/image-templates`,
      form,
      {
        params: { screen_w: screen?.w ?? 0, screen_h: screen?.h ?? 0 },
        headers: { 'Content-Type': 'multipart/form-data' }
      }
    );
    return r.data;
  },

  getImageTemplateUrl: (scenarioId: string, key: string) =>
    farmApi
      .get<{ url: string }>(`/scenarios/${scenarioId}/image-templates/url`, {
        params: { key }
      })
      .then((r) => r.data.url)
};

export type ImageTemplateUploadOut = {
  template_key: string;
  size_bytes: number;
  screen_w: number | null;
  screen_h: number | null;
  /** Empty when the crop looks distinctive enough to match reliably. */
  warning: string;
};
