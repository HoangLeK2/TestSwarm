import { farmApi } from '@/lib/farm-api';
import type {
  ScheduleCreate,
  ScheduleOut,
  SchedulePatch,
  ScheduleRunOut,
  TriggerResponse
} from '../../device-farm/services/generated/DeviceFarmApi';

export type {
  ScheduleCreate,
  ScheduleOut,
  SchedulePatch,
  ScheduleRunOut,
  TriggerResponse
};

export const schedulesApi = {
  list: (query?: { offset?: number; limit?: number }) =>
    farmApi
      .get<ScheduleOut[]>('/schedules', {
        params: query
      })
      .then((r) => r.data),

  get: (scheduleId: string) =>
    farmApi.get<ScheduleOut>(`/schedules/${scheduleId}`).then((r) => r.data),

  create: (data: ScheduleCreate) =>
    farmApi.post<ScheduleOut>('/schedules', data).then((r) => r.data),

  update: (scheduleId: string, data: SchedulePatch) =>
    farmApi
      .patch<ScheduleOut>(`/schedules/${scheduleId}`, data)
      .then((r) => r.data),

  delete: (scheduleId: string) =>
    farmApi.delete(`/schedules/${scheduleId}`).then(() => undefined),

  toggle: (scheduleId: string) =>
    farmApi
      .post<ScheduleOut>(`/schedules/${scheduleId}/toggle`, {})
      .then((r) => r.data),

  runNow: (scheduleId: string) =>
    farmApi
      .post<TriggerResponse>(`/schedules/${scheduleId}/run-now`, {})
      .then((r) => r.data),

  listRuns: (scheduleId: string, query?: { offset?: number; limit?: number }) =>
    farmApi
      .get<ScheduleRunOut[]>(`/schedules/${scheduleId}/runs`, {
        params: query
      })
      .then((r) => r.data),

  getRun: (scheduleId: string, runId: string) =>
    farmApi
      .get<ScheduleRunOut>(`/schedules/${scheduleId}/runs/${runId}`)
      .then((r) => r.data)
};

