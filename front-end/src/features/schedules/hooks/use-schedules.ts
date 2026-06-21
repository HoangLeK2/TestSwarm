import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  schedulesApi,
  type ScheduleCreate,
  type ScheduleOut,
  type SchedulePatch,
  type ScheduleRunOut
} from '../services/api';

const KEYS = {
  list: ['schedules'] as const,
  runs: (scheduleId: string) => ['schedule-runs', scheduleId] as const,
  run: (scheduleId: string, runId: string) =>
    ['schedule-run', scheduleId, runId] as const
};

export function useSchedules() {
  return useQuery({
    queryKey: KEYS.list,
    queryFn: () => schedulesApi.list(),
    staleTime: 5_000
  });
}

export function useScheduleRuns(
  scheduleId: string | null | undefined,
  enabled = true
) {
  return useQuery({
    queryKey: scheduleId ? KEYS.runs(scheduleId) : KEYS.runs('__none__'),
    queryFn: () => schedulesApi.listRuns(scheduleId!),
    enabled: enabled && !!scheduleId,
    staleTime: 2_000,
    refetchInterval: (query) => {
      const data = query.state.data as ScheduleRunOut[] | undefined;
      return data && data.some((r) => ['pending', 'running'].includes(r.status))
        ? 2000
        : false;
    }
  });
}

export function useScheduleRun(
  scheduleId: string | null | undefined,
  runId: string | null | undefined
) {
  return useQuery({
    queryKey:
      scheduleId && runId
        ? KEYS.run(scheduleId, runId)
        : KEYS.run('__none__', '__none__'),
    queryFn: () => schedulesApi.getRun(scheduleId!, runId!),
    enabled: !!scheduleId && !!runId
  });
}

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ScheduleCreate) => schedulesApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useUpdateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      scheduleId,
      data
    }: {
      scheduleId: string;
      data: SchedulePatch;
    }) => schedulesApi.update(scheduleId, data),
    onSuccess: (_, { scheduleId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.runs(scheduleId) });
    }
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: string) => schedulesApi.delete(scheduleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
    }
  });
}

export function useToggleSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      scheduleId,
      enabled
    }: {
      scheduleId: string;
      enabled: boolean;
    }) => {
      // Backend toggles based on current state, so we just call toggle and rely on returned is_enabled.
      return schedulesApi.toggle(scheduleId);
    },
    onSuccess: (_, { scheduleId }) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.runs(scheduleId) });
    }
  });
}

export function useRunNowSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: string) => schedulesApi.runNow(scheduleId),
    onSuccess: (_, scheduleId) => {
      qc.invalidateQueries({ queryKey: KEYS.list });
      qc.invalidateQueries({ queryKey: KEYS.runs(scheduleId) });
      qc.invalidateQueries({ queryKey: ['campaigns'] });
      void qc.refetchQueries({ queryKey: ['campaigns'] });
    }
  });
}

export type { ScheduleOut, ScheduleRunOut };
