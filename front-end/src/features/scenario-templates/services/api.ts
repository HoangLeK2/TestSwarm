import { farmApi } from '@/lib/farm-api';
import type {
  ScenarioTemplateOut,
  ScenarioTemplateCreate,
  ScenarioTemplateUpdate
} from '../../device-farm/services/generated/DeviceFarmApi';

export type {
  ScenarioTemplateOut,
  ScenarioTemplateCreate,
  ScenarioTemplateUpdate
};

export const scenarioTemplatesApi = {
  list: (query?: { category?: string; tags?: string }) =>
    farmApi
      .get<ScenarioTemplateOut[]>('/scenario-templates', { params: query })
      .then((r) => r.data),
  get: (templateId: string) =>
    farmApi
      .get<ScenarioTemplateOut>(`/scenario-templates/${templateId}`)
      .then((r) => r.data),
  create: (data: ScenarioTemplateCreate) =>
    farmApi
      .post<ScenarioTemplateOut>('/scenario-templates', data)
      .then((r) => r.data),
  update: (templateId: string, data: ScenarioTemplateUpdate) =>
    farmApi
      .patch<ScenarioTemplateOut>(`/scenario-templates/${templateId}`, data)
      .then((r) => r.data),
  delete: (templateId: string) =>
    farmApi.delete(`/scenario-templates/${templateId}`).then((r) => r.data),
  duplicate: (templateId: string) =>
    farmApi
      .post<ScenarioTemplateOut>(`/scenario-templates/${templateId}/duplicate`)
      .then((r) => r.data)
};
