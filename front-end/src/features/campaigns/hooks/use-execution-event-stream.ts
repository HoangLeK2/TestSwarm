'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { deviceFarmBackendBase } from '@/lib/farm-api';
import { consumeSseStream } from '@/lib/sse-stream';
import { tokenStorage } from '@/lib/token-storage';
import type { ExecutionEventOut } from '../../device-farm/services/generated/DeviceFarmApi';
import {
  foldEventsToProgress,
  foldEventsToStepLog,
  parseExecutionEventEnvelope
} from '../lib/execution-event-utils';
import type { StepLogEntry, WorkflowProgress } from '../types';

const CURRENT_ORG_STORAGE_KEY = 'device-farm:current-organization-id';
const RECONNECT_MS = 5_000;

export type ExecutionEventStreamState = {
  events: ExecutionEventOut[];
  connected: boolean;
  error: string | null;
  stepLog: StepLogEntry[];
  progress: Partial<WorkflowProgress> | null;
};

export function useExecutionEventStream(
  executionId: string | undefined,
  options: {
    enabled: boolean;
    workflowId: string;
    deviceSerial: string;
  }
): ExecutionEventStreamState {
  const { enabled, workflowId, deviceSerial } = options;
  const [events, setEvents] = useState<ExecutionEventOut[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastEventIdRef = useRef<string | undefined>(undefined);

  const appendEvent = useCallback((envelope: ExecutionEventOut) => {
    setEvents((prev) => {
      if (prev.some((e) => e.event_id === envelope.event_id)) return prev;
      return [...prev, envelope];
    });
    lastEventIdRef.current = envelope.event_id;
  }, []);

  useEffect(() => {
    if (!enabled || !executionId) {
      setEvents([]);
      setConnected(false);
      setError(null);
      lastEventIdRef.current = undefined;
      return;
    }

    let cancelled = false;
    const abort = new AbortController();

    const abortOnPageExit = () => {
      cancelled = true;
      abort.abort();
    };

    if (typeof window !== 'undefined') {
      window.addEventListener('pagehide', abortOnPageExit);
      window.addEventListener('beforeunload', abortOnPageExit);
    }

    const run = async () => {
      while (!cancelled && !abort.signal.aborted) {
        const headers: Record<string, string> = {};
        const token = tokenStorage.getAuthToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        if (typeof window !== 'undefined') {
          const orgId = localStorage.getItem(CURRENT_ORG_STORAGE_KEY)?.trim();
          if (orgId) headers['X-Organization-Id'] = orgId;
        }

        const base = `${deviceFarmBackendBase.replace(/\/+$/, '')}/api`;
        const url = `${base}/executions/${encodeURIComponent(executionId)}/events/stream`;

        try {
          setError(null);
          await consumeSseStream({
            url,
            headers,
            signal: abort.signal,
            lastEventId: lastEventIdRef.current,
            onOpen: () => {
              if (!cancelled) setConnected(true);
            },
            onMessage: (msg) => {
              if (!msg.data) return;
              const envelope = parseExecutionEventEnvelope(msg.data);
              if (envelope) appendEvent(envelope);
            }
          });
        } catch (err) {
          if (abort.signal.aborted || cancelled) return;
          setConnected(false);
          setError(err instanceof Error ? err.message : 'SSE disconnected');
          await new Promise((r) => setTimeout(r, RECONNECT_MS));
          continue;
        }

        if (!cancelled && !abort.signal.aborted) {
          setConnected(false);
          await new Promise((r) => setTimeout(r, RECONNECT_MS));
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
      abort.abort();
      setConnected(false);
      if (typeof window !== 'undefined') {
        window.removeEventListener('pagehide', abortOnPageExit);
        window.removeEventListener('beforeunload', abortOnPageExit);
      }
    };
  }, [appendEvent, enabled, executionId]);

  const stepLog = useMemo(() => foldEventsToStepLog(events), [events]);
  const progress = useMemo(
    () => foldEventsToProgress(events, workflowId, deviceSerial),
    [events, workflowId, deviceSerial]
  );

  return { events, connected, error, stepLog, progress };
}
