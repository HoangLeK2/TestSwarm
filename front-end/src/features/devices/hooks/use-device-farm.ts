'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import type { Device, Task, WsMessage } from '../types';
import { createWs } from '../services/ws';
import { fetchConfig, fetchLiveDevices, fetchTasks } from '../services/api';
import { devicesApi, type DeviceOut } from '../services/manage-api';
import { filterVisibleDeviceFarmDevices } from '../lib/device-farm-visible-devices';
import { useConfirm } from '@/providers/modal-provider';
import { useOrganization } from '@/features/organization/hooks/use-organization';
import { useTabNetworkActive } from './use-tab-network-active';

export function useDeviceFarm() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [registeredDevices, setRegisteredDevices] = useState<DeviceOut[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [modes, setModes] = useState<Record<string, 'tap' | 'swipe'>>({});
  const [wifiDenseposeUrl, setWifiDenseposeUrl] = useState<string | null>(null);

  const wsRef = useRef<ReturnType<typeof createWs> | null>(null);
  const t = useTranslations('devicesFarm');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { currentOrg } = useOrganization();
  const currentOrgId = currentOrg?.id ?? null;
  const tabActive = useTabNetworkActive();

  const wsSend = useCallback((obj: object) => wsRef.current?.send(obj), []);
  const refreshTasks = useCallback(() => {
    if (!tabActive) return;
    fetchTasks()
      .then((data) => setTasks(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, [tabActive]);

  const refreshDevices = useCallback(() => {
    if (!tabActive) return;
    if (!currentOrgId) return;
    fetchLiveDevices(undefined)
      .then((live) => setDevices(live))
      .catch(() => {});
    devicesApi
      .list()
      .then((list) => setRegisteredDevices(list))
      .catch(() => {});
  }, [currentOrgId, tabActive]);

  useEffect(() => {
    refreshDevices();
  }, [refreshDevices]);

  useEffect(() => {
    setDevices([]);
    setRegisteredDevices([]);
  }, [currentOrgId]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        refreshDevices();
        refreshTasks();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('focus', refreshDevices);
    window.addEventListener('focus', refreshTasks);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('focus', refreshDevices);
      window.removeEventListener('focus', refreshTasks);
    };
  }, [refreshDevices, refreshTasks]);

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
        return;
      }

      if (msg.type === 'status' && 'serial' in msg) {
        setDevices((prev) => {
          const exists = prev.some((d) => d.serial === msg.serial);
          if (!exists) {
            return [
              ...prev,
              {
                serial: msg.serial,
                brand: msg.brand ?? '',
                model: msg.model ?? '',
                state: msg.state ?? 'CONNECTING',
                battery: msg.battery ?? -1,
                current_app: msg.current_app ?? '',
                screen_width: msg.device_width ?? msg.screen_width ?? 1080,
                screen_height: msg.device_height ?? msg.screen_height ?? 1920,
                touch_method: msg.touch_method,
                minitouch_ready: msg.minitouch_ready,
                u2_ready: msg.u2_ready,
                scenario_active: msg.scenario_active ?? 0
              }
            ];
          }
          return prev.map((d) =>
            d.serial === msg.serial
              ? {
                  ...d,
                  state: msg.state ?? d.state,
                  battery: msg.battery ?? d.battery,
                  current_app: msg.current_app ?? d.current_app,
                  screen_width:
                    msg.device_width ?? msg.screen_width ?? d.screen_width,
                  screen_height:
                    msg.device_height ?? msg.screen_height ?? d.screen_height,
                  touch_method: msg.touch_method ?? d.touch_method,
                  minitouch_ready: msg.minitouch_ready ?? d.minitouch_ready,
                  u2_ready: msg.u2_ready ?? d.u2_ready,
                  scenario_active:
                    'scenario_active' in msg
                      ? (msg.scenario_active ?? 0)
                      : d.scenario_active
                }
              : d
          );
        });
        // If we see a new device via WebSocket that is now registered, update serial set
        setRegisteredDevices((prev) => {
          if (prev.some((d) => d.serial === msg.serial)) return prev;
          devicesApi
            .list()
            .then((list) => setRegisteredDevices(list))
            .catch(() => {});
          return prev;
        });
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
  }, [tabActive]);

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
