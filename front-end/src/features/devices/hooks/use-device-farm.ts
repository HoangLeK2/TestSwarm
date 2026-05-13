'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import type { Device, Task, WsMessage } from '../types';
import { createWs } from '../services/ws';
import { fetchConfig, fetchLiveDevices, fetchTasks } from '../services/api';
import { devicesApi } from '../services/manage-api';
import { useConfirm } from '@/providers/modal-provider';

export function useDeviceFarm() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [registeredSerials, setRegisteredSerials] = useState<Set<string>>(new Set());
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

  const wsSend = useCallback((obj: object) => wsRef.current?.send(obj), []);
  const refreshTasks = useCallback(() => {
    fetchTasks()
      .then((data) => setTasks(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  // Fetch user's registered devices to filter the live list
  useEffect(() => {
    devicesApi.list()
      .then((list) => setRegisteredSerials(new Set(list.map((d) => d.serial))))
      .catch(() => {});
  }, []);

  // Fetch live device list on mount AND on page focus/visibility change
  const refreshDevices = useCallback(() => {
    fetchLiveDevices()
      .then((live) => setDevices(live))
      .catch(() => {});
    devicesApi.list()
      .then((list) => setRegisteredSerials(new Set(list.map((d) => d.serial))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshDevices();
  }, [refreshDevices]);

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
                serial:           msg.serial,
                brand:            msg.brand ?? '',
                model:            msg.model ?? '',
                state:            msg.state ?? 'CONNECTING',
                battery:          msg.battery ?? -1,
                current_app:      msg.current_app ?? '',
                screen_width:     msg.device_width ?? msg.screen_width ?? 1080,
                screen_height:    msg.device_height ?? msg.screen_height ?? 1920,
                touch_method:     msg.touch_method,
                minitouch_ready:  msg.minitouch_ready,
                u2_ready:         msg.u2_ready,
                scenario_active:  msg.scenario_active ?? 0,
              },
            ];
          }
          return prev.map((d) =>
            d.serial === msg.serial
              ? {
                  ...d,
                  state:            msg.state ?? d.state,
                  battery:          msg.battery ?? d.battery,
                  current_app:     msg.current_app ?? d.current_app,
                  screen_width:    msg.device_width ?? msg.screen_width ?? d.screen_width,
                  screen_height:   msg.device_height ?? msg.screen_height ?? d.screen_height,
                  touch_method:    msg.touch_method ?? d.touch_method,
                  minitouch_ready: msg.minitouch_ready ?? d.minitouch_ready,
                  u2_ready:        msg.u2_ready ?? d.u2_ready,
                  scenario_active: msg.scenario_active ?? d.scenario_active,
                }
              : d
          );
        });
        // If we see a new device via WebSocket that is now registered, update serial set
        setRegisteredSerials((prev) => {
          if (prev.has(msg.serial)) return prev;
          // Re-fetch to pick up newly paired devices
          devicesApi.list().then((list) =>
            setRegisteredSerials(new Set(list.map((d) => d.serial)))
          ).catch(() => {});
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

    });

    return () => wsRef.current?.close();
  }, []);

  const handleToggleMode = useCallback((serial: string) => {
    setModes((prev) => ({
      ...prev,
      [serial]: prev[serial] === 'tap' ? 'swipe' : 'tap',
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

  const myDevices = devices.filter((device) => registeredSerials.has(device.serial));

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
    handleRestart,
  };
}
