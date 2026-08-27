'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import type { Device, Task, WsMessage } from '../types';
import { createWs } from '../services/ws';
import { fetchConfig, fetchLiveDevices, fetchTasks } from '../services/api';
import { devicesApi, type DeviceOut } from '../services/manage-api';
import { filterVisibleDeviceFarmDevices } from '../lib/device-farm-visible-devices';
import { mergeLiveDeviceSnapshot } from '../lib/device-farm-live-snapshot';
import { mergeDeviceFarmWsStatus } from '../lib/device-farm-ws-status';
import { useConfirm } from '@/providers/modal-provider';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { useTabNetworkActive } from './use-tab-network-active';
import { isAxiosError } from 'axios';

const LIVE_DEVICE_REFRESH_MS = 5_000;

export type DeviceFarmRequestStatus = 'idle' | 'loading' | 'success' | 'error';

type UseDeviceFarmOptions = {
  liveRefreshMs?: number | false;
  loadTasks?: boolean;
  loadRegisteredDevices?: boolean;
  refreshRegisteredOnFocus?: boolean;
  liveSnapshotAuthoritative?: boolean;
};

export function useDeviceFarm(options: UseDeviceFarmOptions = {}) {
  const liveRefreshMs = options.liveRefreshMs ?? LIVE_DEVICE_REFRESH_MS;
  const loadTasks = options.loadTasks ?? true;
  const loadRegisteredDevices = options.loadRegisteredDevices ?? true;
  const refreshRegisteredOnFocus = options.refreshRegisteredOnFocus ?? true;
  const liveSnapshotAuthoritative = options.liveSnapshotAuthoritative ?? false;
  const [devices, setDevices] = useState<Device[]>([]);
  const [registeredDevices, setRegisteredDevices] = useState<DeviceOut[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [modes, setModes] = useState<Record<string, 'tap' | 'swipe'>>({});
  const [wifiDenseposeUrl, setWifiDenseposeUrl] = useState<string | null>(null);
  const [devicesReady, setDevicesReady] = useState(false);
  const [requestStatus, setRequestStatus] =
    useState<DeviceFarmRequestStatus>('idle');
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

  const wsRef = useRef<ReturnType<typeof createWs> | null>(null);
  const t = useTranslations('devicesFarm');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { currentOrg } = useOrganization();
  const currentOrgId = currentOrg?.id ?? null;
  const tabActive = useTabNetworkActive();

  const wsSend = useCallback((obj: object) => wsRef.current?.send(obj), []);
  const refreshTasks = useCallback(() => {
    if (!loadTasks) return;
    if (!tabActive) return;
    fetchTasks()
      .then((data) => setTasks(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, [loadTasks, tabActive]);

  const refreshDevices = useCallback(async () => {
    if (!tabActive || !currentOrgId) return;
    setRequestStatus((current) =>
      current === 'success' ? current : 'loading'
    );
    try {
      const live = await fetchLiveDevices({ orgId: currentOrgId });
      setDevices((previous) => mergeLiveDeviceSnapshot(previous, live));
      setDevicesReady(true);
      setRequestStatus('success');
      setError(null);
      setLastUpdatedAt(new Date().toISOString());
    } catch (cause) {
      const status = isAxiosError(cause) ? cause.response?.status : undefined;
      const requestId = isAxiosError(cause)
        ? String(cause.response?.headers?.['x-request-id'] ?? '').trim()
        : '';
      const baseMessage =
        cause instanceof Error ? cause.message : String(cause);
      const message = [
        status ? `HTTP ${status}` : '',
        requestId ? `request ${requestId}` : '',
        baseMessage
      ]
        .filter(Boolean)
        .join(' - ');
      setError(message || t('backendErrorTitle'));
      setRequestStatus('error');
    }
  }, [currentOrgId, t, tabActive]);

  const refreshRegisteredDevices = useCallback(() => {
    if (!loadRegisteredDevices) return;
    if (!tabActive) return;
    if (!currentOrgId) return;
    devicesApi
      .list()
      .then((list) => setRegisteredDevices(list))
      .catch(() => {});
  }, [currentOrgId, loadRegisteredDevices, tabActive]);

  useEffect(() => {
    refreshDevices();
    refreshRegisteredDevices();
  }, [refreshDevices, refreshRegisteredDevices]);

  useEffect(() => {
    if (!tabActive || !currentOrgId) return;
    if (liveRefreshMs === false) return;
    const timer = window.setInterval(refreshDevices, liveRefreshMs);
    return () => window.clearInterval(timer);
  }, [currentOrgId, liveRefreshMs, refreshDevices, tabActive]);

  useEffect(() => {
    setDevices([]);
    setRegisteredDevices([]);
    setDevicesReady(false);
    setRequestStatus(currentOrgId ? 'loading' : 'idle');
    setError(null);
    setLastUpdatedAt(null);
  }, [currentOrgId]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        refreshDevices();
        if (loadRegisteredDevices && refreshRegisteredOnFocus)
          refreshRegisteredDevices();
        refreshTasks();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('focus', refreshDevices);
    if (loadRegisteredDevices && refreshRegisteredOnFocus) {
      window.addEventListener('focus', refreshRegisteredDevices);
    }
    window.addEventListener('focus', refreshTasks);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('focus', refreshDevices);
      if (loadRegisteredDevices && refreshRegisteredOnFocus) {
        window.removeEventListener('focus', refreshRegisteredDevices);
      }
      window.removeEventListener('focus', refreshTasks);
    };
  }, [
    refreshDevices,
    refreshRegisteredDevices,
    loadRegisteredDevices,
    refreshRegisteredOnFocus,
    refreshTasks
  ]);

  useEffect(() => {
    fetchConfig()
      .then((c) => setWifiDenseposeUrl(c.wifi_densepose_url ?? null))
      .catch(() => setWifiDenseposeUrl(null));
  }, []);

  useEffect(() => {
    refreshTasks();
  }, [refreshTasks]);

  useEffect(() => {
    if (!tabActive) {
      wsRef.current?.close();
      wsRef.current = null;
      setWsConnected(false);
      return;
    }
    wsRef.current = createWs((msg: WsMessage) => {
      if (msg.type === 'ws_status') {
        setWsConnected(msg.connected);
        if (msg.connected) queueMicrotask(refreshDevices);
        return;
      }

      if (msg.type === 'status' && 'serial' in msg) {
        setDevices((prev) => {
          return mergeDeviceFarmWsStatus(prev, msg, {
            liveSnapshotAuthoritative
          });
        });
        if (loadRegisteredDevices) {
          // If we see a new device via WebSocket that is now registered, update serial set
          setRegisteredDevices((prev) => {
            if (prev.some((d) => d.serial === msg.serial)) return prev;
            devicesApi
              .list()
              .then((list) => setRegisteredDevices(list))
              .catch(() => {});
            return prev;
          });
        }
        return;
      }

      if (msg.type === 'log' && 'serial' in msg && 'line' in msg) {
        setLogs((prev) => {
          const arr = [...(prev[msg.serial] ?? []), msg.line].slice(-50);
          return { ...prev, [msg.serial]: arr };
        });
      }

      if (msg.type === 'multi_action_result') {
        setLogs((prev) => {
          const next = { ...prev };
          msg.results.forEach((item) => {
            const status = item.ok ? 'ok' : item.error || 'failed';
            const latency =
              typeof item.latency_ms === 'number'
                ? ` ${item.latency_ms}ms`
                : '';
            next[item.serial] = [
              ...(next[item.serial] ?? []),
              `[multi] ${status}${latency}`
            ].slice(-50);
          });
          return next;
        });
      }
    });

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [
    liveSnapshotAuthoritative,
    loadRegisteredDevices,
    refreshDevices,
    tabActive
  ]);

  const handleToggleMode = useCallback((serial: string) => {
    setModes((prev) => ({
      ...prev,
      [serial]: prev[serial] === 'tap' ? 'swipe' : 'tap'
    }));
  }, []);

  const handleRestart = useCallback(
    (serial: string) => {
      void (async () => {
        const ok = await confirm({
          title: t('restartDeviceConfirmTitle'),
          description: t('restartDeviceConfirmDescription', { serial }),
          confirmText: tCommon('confirm'),
          cancelText: tCommon('cancel'),
          zIndex: 10_000
        });
        if (!ok) return;
        wsSend({ type: 'restart', serial });
      })();
    },
    [confirm, t, tCommon, wsSend]
  );

  const myDevices = useMemo(
    () => filterVisibleDeviceFarmDevices(devices, registeredDevices),
    [devices, registeredDevices]
  );

  return {
    devices: myDevices,
    devicesReady,
    requestStatus,
    lastUpdatedAt,
    refreshDevices,
    tasks,
    wsConnected,
    error,
    logs,
    modes,
    wifiDenseposeUrl,
    wsSend,
    handleToggleMode,
    handleRestart
  };
}
